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

function recordingChildCommand(pidPath: string, signalPath: string): string {
	const program = [
		"const fs = require('node:fs')",
		`fs.writeFileSync(${JSON.stringify(pidPath)}, String(process.pid))`,
		"let exitTimer",
		"for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {",
		"  process.on(signal, () => {",
		`    fs.appendFileSync(${JSON.stringify(signalPath)}, signal + '\\n')`,
		"    exitTimer ??= setTimeout(() => process.exit(0), 200)",
		"  })",
		"}",
		"setInterval(() => {}, 1_000)",
	].join(";");
	const encoded = Buffer.from(program).toString("base64");
	return `exec node -e 'eval(Buffer.from("${encoded}", "base64").toString())'`;
}

function startTerminalLauncher(backend: string, frontend: string) {
	const child = spawn("bash", ["scripts/run-local-codex.sh"], {
		cwd: root,
		detached: true,
		env: {
			...process.env,
			PATH: `${path.join(root, "node_modules", ".bin")}:${process.env.PATH ?? ""}`,
			LOCAL_BACKEND_COMMAND: backend,
			LOCAL_FRONTEND_COMMAND: frontend,
			LOCAL_LAUNCHER_GRACE_SECONDS: "0.25",
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

const terminalInterruptDirectory = mkdtempSync(
	path.join(tmpdir(), "voice-acp-launcher-terminal-"),
);
try {
	const backendPidPath = path.join(terminalInterruptDirectory, "backend.pid");
	const frontendPidPath = path.join(terminalInterruptDirectory, "frontend.pid");
	const backendSignals = path.join(
		terminalInterruptDirectory,
		"backend.signals",
	);
	const frontendSignals = path.join(
		terminalInterruptDirectory,
		"frontend.signals",
	);
	const launcherProcess = startTerminalLauncher(
		recordingChildCommand(backendPidPath, backendSignals),
		recordingChildCommand(frontendPidPath, frontendSignals),
	);
	const [backendPid, frontendPid] = await Promise.all([
		waitForPid(backendPidPath),
		waitForPid(frontendPidPath),
	]);

	process.kill(-launcherProcess.pid, "SIGINT");
	const result = await launcherProcess.exited;

	assert(
		result.code === 130 && result.signal === null,
		"terminal SIGINT should be owned and return status 130",
	);
	assert(
		!result.output.includes("Traceback"),
		"terminal SIGINT should not print a traceback",
	);
	const observedBackendSignals = readFileSync(backendSignals, "utf8").trim();
	const observedFrontendSignals = readFileSync(frontendSignals, "utf8").trim();
	assert(
		observedBackendSignals === "SIGINT",
		`backend should receive one SIGINT, received ${JSON.stringify(observedBackendSignals)}`,
	);
	assert(
		observedFrontendSignals === "SIGINT",
		`frontend should receive one SIGINT, received ${JSON.stringify(observedFrontendSignals)}`,
	);
	await Promise.all([waitForExit(backendPid), waitForExit(frontendPid)]);
} finally {
	rmSync(terminalInterruptDirectory, { recursive: true, force: true });
}

console.log("Local launcher cleanup integration checks passed");
