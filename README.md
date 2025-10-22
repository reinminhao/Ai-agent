# AI Agent: 代码功能定位报告服务

## 功能概述
- 接收 `multipart/form-data`
  - `problem_description` 字段:自然语言功能描述
  - `code_zip` 文件: 完整源码的zip压缩包
- 输出JSON报告, 指出各功能在仓库中的关键实现文件、函数与行号
- 资源与内存安全: 临时目录、文件句柄与内存显式回收


