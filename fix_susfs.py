#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""susfs 4.19 补丁在 realme GT Neo 2 (Oplus 4.19.157) 源码上的手工适配。

官方 susfs 补丁 (50_add_susfs_in_kernel-4.19.patch) 有 5 个文件与 realme
修改过的源码不匹配而打不上:
  fs/namespace.c        -> 本脚本补插 (includes + 声明块, 位置随 Oplus 代码调整)
  fs/proc/task_mmu.c    -> 本脚本补插 (susfs_def.h include)
  fs/readdir.c          -> 本脚本补插 (compat_fillonedir 的 sus_path 检查;
                           realme 该函数是老变体, 无 verify_dirent_name)
  include/linux/sched.h -> 本脚本补插 (realme 无 ANDROID_KABI_RESERVE(6)/(8),
                           直接以普通 u64 字段加在 randomized_struct_fields_end 前)
  fs/notify/fdinfo.c    -> 跳过 (realme 的 inotify_fdinfo 变体没有 file 指针
                           且 seq_printf 格式不同, 该 hunk 无法等价移植;
                           仅影响 inotify fdinfo 层面的路径隐藏, 不影响核心功能)

所有插入均为幂等操作, 可重复运行。
"""
import pathlib
import sys


def insert(path, anchor, block, before=False, find_from=None):
    p = pathlib.Path(path)
    if not p.exists():
        print(f"SKIP missing file: {path}")
        return
    text = p.read_text()
    if block.strip() and block.strip() in text:
        print(f"SKIP already patched: {path}")
        return
    if anchor not in text:
        print(f"FATAL anchor not found in {path}: {anchor!r}")
        sys.exit(1)
    if find_from is not None:
        start = text.index(find_from)
        rel = text.index(anchor, start)
        idx = rel if before else rel + len(anchor)
    else:
        idx = text.index(anchor)
        if not before:
            idx += len(anchor)
    text = text[:idx] + block + text[idx:]
    p.write_text(text)
    print(f"OK patched: {path}")


# ---- 1. fs/namespace.c ----
insert(
    "fs/namespace.c",
    "#include <linux/sched/task.h>\n",
    "\n#if defined(CONFIG_KSU_SUSFS_SUS_MOUNT) || defined(CONFIG_KSU_SUSFS_TRY_UMOUNT)\n"
    "#include <linux/susfs_def.h>\n"
    "#endif\n",
)

ns_decl = (
    "\n#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    "extern bool susfs_is_current_ksu_domain(void);\n"
    "extern bool susfs_is_current_zygote_domain(void);\n"
    "\n"
    "static DEFINE_IDA(susfs_mnt_id_ida);\n"
    "static DEFINE_IDA(susfs_mnt_group_ida);\n"
    "\n"
    "#define CL_ZYGOTE_COPY_MNT_NS BIT(24) /* used by copy_mnt_ns() */\n"
    "#define CL_COPY_MNT_NS BIT(25) /* used by copy_mnt_ns() */\n"
    "#endif\n"
    "\n"
    "#ifdef CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT\n"
    "extern void susfs_auto_add_sus_ksu_default_mount(const char __user *to_pathname);\n"
    "bool susfs_is_auto_add_sus_ksu_default_mount_enabled = true;\n"
    "#endif\n"
    "#ifdef CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT\n"
    "extern int susfs_auto_add_sus_bind_mount(const char *pathname, struct path *path_target);\n"
    "bool susfs_is_auto_add_sus_bind_mount_enabled = true;\n"
    "#endif\n"
    "#ifdef CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT\n"
    "extern void susfs_auto_add_try_umount_for_bind_mount(struct path *path);\n"
    "bool susfs_is_auto_add_try_umount_for_bind_mount_enabled = true;\n"
    "#endif\n"
)
# 插在 Oplus SECURITY_GUARD 块之后、sysctl_mount_max 之前
insert(
    "fs/namespace.c",
    "#endif /* CONFIG_OPLUS_SECURE_GUARD*/\n",
    ns_decl,
)

# ---- 2. fs/proc/task_mmu.c ----
insert(
    "fs/proc/task_mmu.c",
    "#include <linux/mm_inline.h>\n",
    "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n"
    "#include <linux/susfs_def.h>\n"
    "#endif\n",
)

# ---- 3. fs/readdir.c (仅 compat_fillonedir) ----
readdir_block = (
    "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
    "\tif (likely(current->susfs_task_state & TASK_STRUCT_NON_ROOT_USER_APP_PROC) && susfs_sus_ino_for_filldir64(ino)) {\n"
    "\t\treturn 0;\n"
    "\t}\n"
    "#endif\n"
)
# 从 compat_fillonedir 函数体内查找, 避免误插入到同样模式的 filldir()
insert(
    "fs/readdir.c",
    "\t\treturn -EINVAL;\n",
    readdir_block,
    find_from="static int compat_fillonedir",
)

# ---- 4. include/linux/sched.h ----
insert(
    "include/linux/sched.h",
    "\trandomized_struct_fields_end\n",
    "#if defined(CONFIG_KSU_SUSFS)\n"
    "\tu64 susfs_task_state;\n"
    "\tu64 susfs_last_fake_mnt_id;\n"
    "#endif\n\n",
    before=True,
)

print("susfs realme adaptation done")
