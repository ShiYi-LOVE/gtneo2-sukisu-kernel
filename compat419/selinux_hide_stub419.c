/* SPDX-License-Identifier: GPL-2.0 */
/*
 * OPLUS 4.19 COMPAT: feature/selinux_hide.c 的空实现
 *
 * 原文件整套建立在 Linux 5.7+ 的 SELinux 策略架构上:
 *   - struct selinux_policy (策略是"可替换的指针", selinux_state.policy)
 *   - security_context_to_sid_with_policy() / security_compute_av_user_with_policy()
 *   - backup_sepolicy 备份策略 + sidtab_destroy()
 * 4.19 里 policydb 是内联在 selinux_state.ss 中的, 没有可替换的指针,
 * 也没有 *_with_policy 一族函数 —— 那套东西无处安放, 强行移植等于重写。
 *
 * selinux_hide 的作用是"对被读取的 /sys/fs/selinux/policy 做过滤,
 * 让 su 类型上新增的 allow 规则不显示", 属于反检测增强, 不是 root 的必要条件:
 * 关掉后 su 提权、susfs 隐藏路径都正常, 唯一区别是审计工具从
 * /sys/fs/selinux/policy 里能看到 su 类型比原厂多了几条 allow。
 *
 * 直接在 4.19 上编译原文件会报:
 *   error: no member named 'policy' in 'struct selinux_state'
 *   error: incomplete definition of type 'struct selinux_policy'
 */
#include <linux/types.h>

void ksu_selinux_hide_init(void)
{
}

void ksu_selinux_hide_exit(void)
{
}

void ksu_selinux_hide_drop_backup_if_unused(void)
{
}

void ksu_selinux_hide_handle_second_stage(void)
{
}

void ksu_selinux_hide_handle_post_fs_data(void)
{
}
