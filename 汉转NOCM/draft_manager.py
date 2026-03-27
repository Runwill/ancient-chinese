"""兼容层：统一重新导出 draft_io 和 folder_manager 的所有公开接口。

已拆分为：
  - draft_io.py       — 文稿 CRUD
  - folder_manager.py — 文件夹树管理
"""

# 文稿操作
from draft_io import (  # noqa: F401
    ensure_drafts_dir, get_drafts_order, save_drafts_order,
    list_drafts, save_draft, load_draft,
    delete_draft, rename_draft, get_draft_name,
)

# 文件夹操作
from folder_manager import (  # noqa: F401
    get_groups, save_groups, create_group,
    rename_group, delete_group, toggle_group,
    move_to_group, remove_from_group, move_group_into,
    get_grouped_filenames, reorder_group, reorder_file_in_group,
)
