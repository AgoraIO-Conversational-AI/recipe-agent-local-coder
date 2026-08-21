const result = Bun.spawnSync([
	"git",
	"ls-files",
	"-z",
	"--",
	"docs/superpowers",
]);

if (result.exitCode !== 0) {
	process.stderr.write(new TextDecoder().decode(result.stderr));
	process.exit(result.exitCode);
}

const tracked = new TextDecoder()
	.decode(result.stdout)
	.split("\0")
	.filter(Boolean);

if (tracked.length > 0) {
	console.error(
		"Public repository verification failed: docs/superpowers must remain local-only.",
	);
	for (const path of tracked) console.error(`- ${path}`);
	process.exit(1);
}

console.log("Public repository boundary check passed");
