"""omni_music 本地音乐库管理子包（M19）。

扩展 omni_music 的本地音乐管理能力，作为插件内能力扩展（不新建插件）：

- :mod:`db`           ：SQLite 音乐库索引（FTS5 全文搜索 / 歌单 / 播放历史）
- :mod:`scanner`      ：增强扫描器（复用 LocalMusicSource + mutagen，提取封面/歌词）
- :mod:`watcher`      ：watchdog 文件监听（防抖 + 后台线程）
- :mod:`decryptor`    ：加密音频解密（.qmc/.mflac，仅已购买内容，D19.1 合规）
- :mod:`long_audio`   ：长音频分析（播客 / DJ mix / 有声书分类）

合规说明（D19.1）：解密模块仅用于解密用户已合法购买的加密音频文件，
不提供破解付费内容能力。仅做格式转换（已购买内容的本地备份格式转换）。
仅个人学习用途。
"""

from __future__ import annotations
