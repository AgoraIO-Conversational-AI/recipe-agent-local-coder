import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

function assert(condition: unknown, message: string): asserts condition {
	if (!condition) throw new Error(message);
}

const root = process.cwd();
const packageJson = JSON.parse(
	readFileSync(path.join(root, "package.json"), "utf8"),
) as {
	scripts?: Record<string, string>;
};
const launcher = path.join(root, "scripts", "run-local-codex.sh");
const supervisor = path.join(root, "scripts", "supervise-local.py");

assert(
	packageJson.scripts?.["dev:codex"] ===
		"bun run dev:codex:check && bash scripts/run-local-codex.sh",
	"dev:codex should delegate sibling lifecycle cleanup to the local launcher",
);
assert(existsSync(launcher), "local launcher script should exist");
assert(existsSync(supervisor), "local process supervisor should exist");

const source = readFileSync(launcher, "utf8");
assert(
	source.includes("exec python3 scripts/supervise-local.py"),
	"launcher should replace itself with the local process supervisor",
);
assert(
	!source.includes("trap cleanup"),
	"launcher should not retain competing shell signal ownership",
);

async function waitForPid(pathname: string): Promise<number> {
	const deadline = Date.now() + 5_000;
	while (Date.now() < deadline) {
		if (existsSync(pathname))
			return Number(readFileSync(pathname, "utf8").trim());
		await Bun.sleep(25);
	}
	throw new Error(`Timed out waiting for child PID at ${pathname}`);
}

async function waitForExit(pid: number): Promise<void> {
	const deadline = Date.now() + 5_000;
	while (Date.now() < deadline) {
		try {
			process.kill(pid, 0);
		} catch (error) {
			if ((error as NodeJS.ErrnoException).code === "ESRCH") return;
			throw error;
		}
		await Bun.sleep(25);
	}
	throw new Error(`Timed out waiting for child ${pid} to exit`);
}

function childCommand(pidPath: string, body: string): string {
	return `sh -c 'echo $$ > "${pidPath}"; ${body}'`;
}

function startLauncher(backend: string, frontend: string, args: string[] = []) {
	return Bun.spawn({
		cmd: ["bash", "scripts/run-local-codex.sh", ...args],
		cwd: process.cwd(),
		env: {
			...process.env,
			PATH: `${path.join(root, "node_modules", ".bin")}:${process.env.PATH ?? ""}`,
			LOCAL_BACKEND_COMMAND: backend,
			LOCAL_FRONTEND_COMMAND: frontend,
		},
		stdout: "ignore",
		stderr: "ignore",
	});
}

function recordingChildCommand(
	pidPath: string,
	signalPath: string,
	exitDelayMs: number | null = 200,
): string {
	const program = [
		"const fs = require('node:fs')",
		`fs.writeFileSync(${JSON.stringify(pidPath)}, String(process.pid))`,
		"let exitTimer",
		"for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {",
		"  process.on(signal, () => {",
		`    fs.appendFileSync(${JSON.stringify(signalPath)}, signal + '\\n')`,
		exitDelayMs === null
			? "    void exitTimer"
			: `    exitTimer ??= setTimeout(() => process.exit(0), ${exitDelayMs})`,
		"  })",
		"}",
		"setInterval(() => {}, 1_000)",
	].join(";");
	const encoded = Buffer.from(program).toString("base64");
	return `exec node -e 'eval(Buffer.from("${encoded}", "base64").toString())'`;
}

function orphaningChildCommand(pidPath: string, signalPath: string): string {
	return `${recordingChildCommand(pidPath, signalPath)} </dev/null >/dev/null 2>&1 & sleep 0.2; exit 0`;
}

function startTerminalLauncher(
	backend: string,
	frontend: string,
	graceSeconds = 0.25,
) {
	const child = spawn("bash", ["scripts/run-local-codex.sh"], {
		cwd: root,
		detached: true,
		env: {
			...process.env,
			PATH: `${path.join(root, "node_modules", ".bin")}:${process.env.PATH ?? ""}`,
			LOCAL_BACKEND_COMMAND: backend,
			LOCAL_FRONTEND_COMMAND: frontend,
			LOCAL_LAUNCHER_GRACE_SECONDS: String(graceSeconds),
		},
		stdio: ["ignore", "pipe", "pipe"],
	});
	let output = "";
	child.stdout.on("data", (chunk) => {
		output += String(chunk);
	});
	child.stderr.on("data", (chunk) => {
		output += String(chunk);
	});
	const exited = new Promise<{
		code: number | null;
		signal: NodeJS.Signals | null;
		output: string;
	}>((resolve) => {
		child.once("close", (code, signal) => resolve({ code, signal, output }));
	});
	assert(
		child.pid !== undefined,
		"detached launcher should expose a process-group id",
	);
	return { pid: child.pid, exited };
}

async function waitForSignal(pathname: string, expected: NodeJS.Signals) {
	const deadline = Date.now() + 5_000;
	while (Date.now() < deadline) {
		if (
			existsSync(pathname) &&
			readFileSync(pathname, "utf8").split("\n").includes(expected)
		) {
			return;
		}
		await Bun.sleep(25);
	}
	throw new Error(`Timed out waiting for ${expected} at ${pathname}`);
}

async function verifyOwnedTerminalSignal(
	terminalSignal: NodeJS.Signals,
	expectedChildSignal: NodeJS.Signals,
	expectedExitCode: number,
) {
	const directory = mkdtempSync(
		path.join(tmpdir(), "voice-acp-launcher-terminal-"),
	);
	try {
		const backendPidPath = path.join(directory, "backend.pid");
		const frontendPidPath = path.join(directory, "frontend.pid");
		const backendSignals = path.join(directory, "backend.signals");
		const frontendSignals = path.join(directory, "frontend.signals");
		const launcherProcess = startTerminalLauncher(
			recordingChildCommand(backendPidPath, backendSignals),
			recordingChildCommand(frontendPidPath, frontendSignals),
		);
		const [backendPid, frontendPid] = await Promise.all([
			waitForPid(backendPidPath),
			waitForPid(frontendPidPath),
		]);

		process.kill(-launcherProcess.pid, terminalSignal);
		const result = await launcherProcess.exited;

		assert(
			result.code === expectedExitCode && result.signal === null,
			`terminal ${terminalSignal} should be owned and return status ${expectedExitCode}`,
		);
		assert(
			!result.output.includes("Traceback"),
			`terminal ${terminalSignal} should not print a traceback`,
		);
		const observedBackendSignals = readFileSync(backendSignals, "utf8").trim();
		const observedFrontendSignals = readFileSync(
			frontendSignals,
			"utf8",
		).trim();
		assert(
			observedBackendSignals === expectedChildSignal,
			`backend should receive one ${expectedChildSignal}, received ${JSON.stringify(observedBackendSignals)}`,
		);
		assert(
			observedFrontendSignals === expectedChildSignal,
			`frontend should receive one ${expectedChildSignal}, received ${JSON.stringify(observedFrontendSignals)}`,
		);
		await Promise.all([waitForExit(backendPid), waitForExit(frontendPid)]);
	} finally {
		rmSync(directory, { recursive: true, force: true });
	}
}

const overrideProcess = startLauncher(
	`sh -c 'test "$VOICE_ACP_WORKSPACE" = "/tmp/voice acp workspace" && test "$VOICE_ACP_COMMAND_JSON" = "[\\"custom-acp\\",\\"--stdio\\"]"'`,
	"sh -c 'trap \"exit 0\" INT TERM; while :; do sleep 1; done'",
	[
		"--workspace",
		"/tmp/voice acp workspace",
		"--acp-command-json",
		'["custom-acp","--stdio"]',
	],
);
assert(
	(await overrideProcess.exited) === 0,
	"advanced launcher overrides should reach children as opaque env values",
);

const invalidArgumentProcess = startLauncher("exit 0", "exit 0", [
	"--unknown-option",
]);
assert(
	(await invalidArgumentProcess.exited) !== 0,
	"unknown launcher arguments should fail closed",
);

const missingConcurrentlyProcess = Bun.spawn({
	cmd: ["/usr/bin/python3", "scripts/supervise-local.py", "true", "true"],
	cwd: root,
	env: { ...process.env, PATH: "/usr/bin:/bin" },
	stdout: "pipe",
	stderr: "pipe",
});
const missingConcurrentlyExit = await missingConcurrentlyProcess.exited;
const missingConcurrentlyError = await new Response(
	missingConcurrentlyProcess.stderr,
).text();
assert(
	missingConcurrentlyExit === 127,
	"a missing concurrently executable should return 127",
);
assert(
	missingConcurrentlyError.trim() ===
		"Could not start the local process supervisor: concurrently was not found",
	"a missing concurrently executable should return one bounded diagnostic",
);

const failedChildDirectory = mkdtempSync(
	path.join(tmpdir(), "voice-acp-launcher-failure-"),
);
try {
	const backendPidPath = path.join(failedChildDirectory, "backend.pid");
	const frontendPidPath = path.join(failedChildDirectory, "frontend.pid");
	const launcherProcess = startLauncher(
		childCommand(backendPidPath, "sleep 0.2; exit 23"),
		childCommand(
			frontendPidPath,
			'trap "exit 0" INT TERM; while :; do sleep 1; done',
		),
	);
	const frontendPid = await waitForPid(frontendPidPath);
	const exitCode = await launcherProcess.exited;

	assert(
		exitCode !== 0,
		"a failing child should produce a failing launcher status",
	);
	await waitForExit(frontendPid);
} finally {
	rmSync(failedChildDirectory, { recursive: true, force: true });
}

for (const signal of ["SIGINT", "SIGTERM"] as const) {
	const signalChildDirectory = mkdtempSync(
		path.join(tmpdir(), "voice-acp-launcher-signal-"),
	);
	try {
		const backendPidPath = path.join(signalChildDirectory, "backend.pid");
		const frontendPidPath = path.join(signalChildDirectory, "frontend.pid");
		const launcherProcess = startLauncher(
			childCommand(
				backendPidPath,
				'trap "exit 0" INT TERM; while :; do sleep 1; done',
			),
			childCommand(
				frontendPidPath,
				'trap "exit 0" INT TERM; while :; do sleep 1; done',
			),
		);
		const [backendPid, frontendPid] = await Promise.all([
			waitForPid(backendPidPath),
			waitForPid(frontendPidPath),
		]);

		process.kill(launcherProcess.pid, signal);
		await launcherProcess.exited;
		await Promise.all([waitForExit(backendPid), waitForExit(frontendPid)]);
	} finally {
		rmSync(signalChildDirectory, { recursive: true, force: true });
	}
}

await verifyOwnedTerminalSignal("SIGINT", "SIGINT", 130);
await verifyOwnedTerminalSignal("SIGTERM", "SIGTERM", 143);
await verifyOwnedTerminalSignal("SIGHUP", "SIGTERM", 129);

const forcedInterruptDirectory = mkdtempSync(
	path.join(tmpdir(), "voice-acp-launcher-forced-interrupt-"),
);
try {
	const backendPidPath = path.join(forcedInterruptDirectory, "backend.pid");
	const frontendPidPath = path.join(forcedInterruptDirectory, "frontend.pid");
	const backendSignals = path.join(forcedInterruptDirectory, "backend.signals");
	const frontendSignals = path.join(
		forcedInterruptDirectory,
		"frontend.signals",
	);
	const launcherProcess = startTerminalLauncher(
		recordingChildCommand(backendPidPath, backendSignals, null),
		recordingChildCommand(frontendPidPath, frontendSignals, null),
		5,
	);
	const [backendPid, frontendPid] = await Promise.all([
		waitForPid(backendPidPath),
		waitForPid(frontendPidPath),
	]);

	process.kill(-launcherProcess.pid, "SIGINT");
	await Promise.all([
		waitForSignal(backendSignals, "SIGINT"),
		waitForSignal(frontendSignals, "SIGINT"),
	]);
	process.kill(-launcherProcess.pid, "SIGINT");
	const result = await launcherProcess.exited;

	assert(
		result.code === 137 && result.signal === null,
		"a second terminal SIGINT should force cleanup and return 137",
	);
	await Promise.all([waitForExit(backendPid), waitForExit(frontendPid)]);
} finally {
	rmSync(forcedInterruptDirectory, { recursive: true, force: true });
}

const deadlineDirectory = mkdtempSync(
	path.join(tmpdir(), "voice-acp-launcher-deadline-"),
);
try {
	const backendPidPath = path.join(deadlineDirectory, "backend.pid");
	const frontendPidPath = path.join(deadlineDirectory, "frontend.pid");
	const backendSignals = path.join(deadlineDirectory, "backend.signals");
	const frontendSignals = path.join(deadlineDirectory, "frontend.signals");
	const launcherProcess = startTerminalLauncher(
		recordingChildCommand(backendPidPath, backendSignals, null),
		recordingChildCommand(frontendPidPath, frontendSignals, null),
		0.25,
	);
	const [backendPid, frontendPid] = await Promise.all([
		waitForPid(backendPidPath),
		waitForPid(frontendPidPath),
	]);

	process.kill(-launcherProcess.pid, "SIGTERM");
	const result = await launcherProcess.exited;

	assert(
		result.code === 137 && result.signal === null,
		"the graceful deadline should force cleanup and return 137",
	);
	await Promise.all([waitForExit(backendPid), waitForExit(frontendPid)]);
} finally {
	rmSync(deadlineDirectory, { recursive: true, force: true });
}

const residualDirectory = mkdtempSync(
	path.join(tmpdir(), "voice-acp-launcher-residual-"),
);
let residualPid: number | null = null;
try {
	const residualPidPath = path.join(residualDirectory, "residual.pid");
	const residualSignals = path.join(residualDirectory, "residual.signals");
	const launcherProcess = startTerminalLauncher(
		orphaningChildCommand(residualPidPath, residualSignals),
		"sleep 30",
	);
	residualPid = await waitForPid(residualPidPath);

	const result = await launcherProcess.exited;

	assert(
		result.code === 0 && result.signal === null,
		"normal root completion should preserve status zero",
	);
	await waitForExit(residualPid);
	assert(
		readFileSync(residualSignals, "utf8").trim() === "SIGTERM",
		"a residual descendant should receive one cleanup SIGTERM",
	);
} finally {
	if (residualPid !== null) {
		try {
			process.kill(residualPid, "SIGKILL");
		} catch {}
	}
	rmSync(residualDirectory, { recursive: true, force: true });
}

console.log("Local launcher cleanup integration checks passed");
