# harness/web/fixtures/

Web 线测试夹具目录（loop-web.md §3）。

- 夹具随用例落地（W1 起）：种子/命令日志 JSON、期望快照、对照输入指纹等。
- 夹具必须可复现：文件内注明生成命令或来源脚本（research/ 或 tools/）。
- 禁止存放"从被测输出反抄"的期望值——期望须由合同/源码/独立手算推导
  （loop-web.md H2）。
