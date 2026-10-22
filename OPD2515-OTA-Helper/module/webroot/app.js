"use strict";
const SCRIPT = "/data/adb/modules/opd2515_ota_helper/bin/ota.sh";
let callbackCounter = 0;
function quote(value) { return "'" + String(value).replace(/'/g, "'\\''") + "'"; }
function shell(command) {
  return new Promise((resolve, reject) => {
    const bridge = globalThis.ksu;
    if (!bridge?.exec) { reject(new Error("请在 KernelSU 管理器的模块 WebUI 中打开。")); return; }
    const name = `ota_cb_${Date.now()}_${callbackCounter++}`;
    globalThis[name] = (errno, stdout, stderr) => {
      delete globalThis[name];
      resolve({errno:Number(errno), stdout:String(stdout || ""), stderr:String(stderr || "")});
    };
    try { bridge.exec(command, "{}", name); }
    catch (error) { delete globalThis[name]; reject(error); }
  });
}
async function run(action) {
  let arg = "";
  if (action === "import") {
    arg = document.querySelector("#digest").value.trim();
    if (!/^[0-9a-f]{64}$/.test(arg)) throw new Error("粘贴电脑报告中的 64 位小写 SHA256。");
  }
  if (action === "apply") {
    arg = document.querySelector("#ack").value.trim();
    if (!/^APPLY_[ab]$/.test(arg)) throw new Error("先检查 OTA，再输入检查结果中的 APPLY_a 或 APPLY_b。");
  }
  const buttons = [...document.querySelectorAll("button[data-action]")];
  buttons.forEach(b => b.disabled = true);
  const activity = document.querySelector("#activity");
  activity.textContent = action === "export" ? "正在备份，请保持页面打开…" : "正在执行，请保持页面打开…";
  try {
    const command = `/system/bin/sh ${quote(SCRIPT)} ${quote(action)}${arg ? " " + quote(arg) : ""}`;
    const result = await shell(command);
    const output = result.stdout + (result.stderr ? "\n" + result.stderr : "");
    document.querySelector(action === "status" ? "#status" : "#result").textContent = output || "没有返回内容";
    activity.textContent = result.errno === 0 ? "操作完成" : "已停止，请查看结果";
    if (action !== "status") document.querySelector("#result").scrollIntoView({block:"nearest",behavior:"smooth"});
  } finally { buttons.forEach(b => b.disabled = false); }
}
document.querySelectorAll("button[data-action]").forEach(button => button.addEventListener("click", () => {
  run(button.dataset.action).catch(error => {
    document.querySelector("#activity").textContent = "已停止";
    document.querySelector("#result").textContent = error.message;
  });
}));
run("status").catch(error => { document.querySelector("#status").textContent = error.message; });
