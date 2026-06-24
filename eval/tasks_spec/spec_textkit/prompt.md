textkit 是一个文本处理小工具库。下面是它应当满足的完整规格。当前实现有多处不符合规格，其中一部分有测试覆盖、一部分没有。请修复 textkit，使其**完全符合下列每一条规格**（注意：测试只覆盖了一部分规格，请逐条核对、不要只依赖测试）。

slugify(s):
- 转为小写；去除首尾空白；内部连续空白（空格、制表符）压成单个连字符 "-"。
- 仅保留小写字母、数字和连字符，其余字符（标点等）一律删除。
- 多个连续连字符合并为一个，并去除首尾连字符。
- 空字符串或纯空白返回 ""。
  例：slugify("  Hello,  World! ") == "hello-world"；slugify("-a--b-") == "a-b"；slugify("") == ""

truncate(s, n):
- 当 len(s) <= n 原样返回；当 len(s) > n 返回前 n 个字符并追加 "…"（单字符 U+2026）。
- 当 n <= 0 返回 ""。
  例：truncate("hello", 3) == "hel…"；truncate("hi", 5) == "hi"；truncate("hello", 0) == ""

parse_bool(s):
- "true"/"1"/"yes"（忽略大小写与首尾空白）返回 True；"false"/"0"/"no" 返回 False。
- 无法识别的输入抛出 ValueError。
  例：parse_bool(" TRUE ") is True；parse_bool("no") is False；parse_bool("maybe") 抛 ValueError
