import { defineConfig, devices } from "@playwright/test";
export default defineConfig({testDir:"./e2e",fullyParallel:true,use:{baseURL:"http://127.0.0.1:3100",trace:"retain-on-failure"},webServer:{command:"npm run dev:test",url:"http://127.0.0.1:3100",reuseExistingServer:false},projects:[{name:"desktop",use:{...devices["Desktop Chrome"]}},{name:"mobile",use:{...devices["iPhone 13"]}}]});
