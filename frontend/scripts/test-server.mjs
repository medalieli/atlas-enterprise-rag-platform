import { spawn } from "node:child_process";
const child = spawn("npm", ["run","dev","--","--hostname","127.0.0.1","--port","3100"], { stdio:"inherit", shell:process.platform === "win32", env:{...process.env,TEST_BYPASS_AUTH:"true"} });
for (const signal of ["SIGINT","SIGTERM"]) process.on(signal,()=>child.kill(signal));
child.on("exit",code=>process.exit(code??0));
