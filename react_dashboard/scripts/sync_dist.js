import fs from "fs";
import path from "path";

const source = path.resolve("dist");
const target = path.resolve("../react_dashboard_dist");

function copyDir(src, dest) {
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(dest, { recursive: true });
  }

  for (const file of fs.readdirSync(src)) {
    const srcPath = path.join(src, file);
    const destPath = path.join(dest, file);

    if (fs.lstatSync(srcPath).isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

console.log("🚀 syncing dist → react_dashboard_dist...");
copyDir(source, target);
console.log("✅ sync complete");