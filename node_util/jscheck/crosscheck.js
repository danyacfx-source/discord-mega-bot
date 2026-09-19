const fs = require("fs");
const src = fs.readFileSync("C:/Users/Admin/Documents/Default Project/discord-mega-bot/app/core/webpanel/panel.js", "utf8");

const builtins = new Set([
  "if","for","while","switch","catch","return","typeof","new","delete","void","in","of","do","else","case","break",
  "continue","throw","yield","await","this","function","async","document","window","localStorage","navigator","fetch",
  "setInterval","clearInterval","setTimeout","clearTimeout","console","confirm","prompt","escapeHtml","relTime","tag",
  "makeEl","api","toast","$","Math","JSON","Object","Array","String","Number","Boolean","RegExp","Date","Promise",
  "setInterval","clearInterval","encodeURIComponent","decodeURIComponent","encodeURI","decodeURI","isNaN","isFinite","parseInt","parseFloat","undefined","null","true","false","window","escape","unescape","globalThis","structuredClone","btoa","atob","FileReader","Blob","encodeURI","decodeURI","copyText","relTime","escapeHtml","relTime2","formatCount","fmtCount","relTime","tag","toast","api","findMember","loadScheduler","bootInit",
]);

const defined = new Set(builtins);
const funcRe = /(?:async\s+)?function\s+([A-Za-z_$][\w$]*)/g;
const nestedRe = /(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\([^)]*\)\s*=>|\(\)\s*=>|async\s*=>)/g;
let m;
while ((m = funcRe.exec(src))) defined.add(m[1]);
while ((m = nestedRe.exec(src))) defined.add(m[1]);

const called = new Set();
const callRe = /([A-Za-z_$][\w$]*)\s*\(/g;
while ((m = callRe.exec(src))) called.add(m[1]);

const unknown = [...called].filter((n) => !defined.has(n) && !/^[A-Z_$][A-Z0-9_$]*$/.test(n)).sort();

console.log("defined functions/vars:", [...defined].length);
console.log("distinct call-sites:", called.size);
if (unknown.length) {
  console.log("POSSIBLY-UNDEFINED (called but not defined):");
  console.log(unknown.join(", "));
} else {
  console.log("OK: no obvious undefined calls");
}
