
## 功能概述
- 接收 `multipart/form-data`
  - `problem_description` 字段:自然语言功能描述
  - `code_zip` 文件:完整源码的zip压缩包
- 输出JSON报告
- 资源与内存安全: 临时目录、文件句柄与内存回收
- 可选加分:`?run_tests=true`时生成最小测试样例建议


