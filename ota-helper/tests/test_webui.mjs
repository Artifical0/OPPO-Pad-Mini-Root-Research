import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
const elements = new Map();
for (const id of ["#digest", "#ack", "#status", "#result", "#activity"]) {
  elements.set(id, {value:"", textContent:"", scrollIntoView(){}});
}
const buttons = ["status","export","import","preview","apply"].map(action => ({dataset:{action}, disabled:false, addEventListener(){}}));
const calls = [];
const context = vm.createContext({
  document:{querySelector:id => elements.get(id), querySelectorAll:() => buttons},
  Date, Promise, Error, String, setTimeout, clearTimeout,
  ksu:{exec(command, options, callback) {calls.push(command); context[callback](0, "fixture response", "");}}
});
vm.runInContext(fs.readFileSync(new URL("../module/webroot/app.js", import.meta.url), "utf8"), context);
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(elements.get("#status").textContent, "fixture response");
let count = calls.length;
elements.get("#digest").value = "'; reboot; #";
await assert.rejects(vm.runInContext('run("import")', context));
assert.equal(calls.length, count);
elements.get("#digest").value = "a".repeat(64);
await vm.runInContext('run("import")', context);
assert.match(calls.at(-1), /'import' 'a{64}'$/);
elements.get("#ack").value = "APPLY_a; reboot";
count = calls.length;
await assert.rejects(vm.runInContext('run("apply")', context));
assert.equal(calls.length, count);
elements.get("#ack").value = "APPLY_a";
await vm.runInContext('run("apply")', context);
assert.match(calls.at(-1), /'apply' 'APPLY_a'$/);
assert.ok(buttons.every(button => !button.disabled));
assert.equal(elements.get("#result").textContent, "fixture response");
assert.equal(Object.keys(context).filter(key => key.startsWith("ota_cb_")).length, 0);
await assert.rejects(vm.runInContext('run("reboot")', context));
let timeoutCallback;
context.setTimeout = callback => { timeoutCallback=callback; return 42; };
context.clearTimeout = () => {};
context.ksu.exec = () => {};
const pending = vm.runInContext('run("apply")', context);
assert.ok(buttons.every(button => button.disabled));
timeoutCallback();
await assert.rejects(pending, /后台可能仍在执行/);
assert.ok(buttons.every(button => !button.disabled));
assert.equal(Object.keys(context).filter(key => key.startsWith("ota_cb_")).length, 0);
console.log("PASS: WebUI callback, hash/ack validation, shell quoting, output and button lifecycle (mock bridge).");
