import json
import re
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import webbrowser
import subprocess
import threading
import requests
import os
import sys
import time

# 导入爬虫逻辑模块
import scan

# --- 配置区：兼容 EXE 打包路径 ---
if getattr(sys, 'frozen', False):
    # 打包后的运行环境
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 普通 Python 运行环境
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_FILE = os.path.join(BASE_DIR, "eve_full_data.json")


# ================= 工具函数与重定向类 =================

def center_window(child, parent, width, height):
    """将窗口居中显示在父窗口中心"""
    parent.update_idletasks()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    x = px + (pw // 2) - (width // 2)
    y = py + (ph // 2) - (height // 2)
    if y < 0: y = 0
    child.geometry(f"{width}x{height}+{x}+{y}")


class RedirectText:
    """将 print 输出实时重定向到 GUI 日志组件"""

    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, string):
        self.text_widget.after(0, self._insert_text, string)

    def _insert_text(self, string):
        self.text_widget.config(state=tk.NORMAL)
        tag = "info"
        if "✅" in string or "成功" in string: tag = "success"
        if "❌" in string or "错误" in string: tag = "error"
        if "⚠️" in string: tag = "warning"
        self.text_widget.insert(tk.END, string, tag)
        self.text_widget.see(tk.END)
        self.text_widget.config(state=tk.DISABLED)

    def flush(self):
        pass


# ================= 自定义弹窗组件 =================

class SimpleListEditDialog(tk.Toplevel):
    def __init__(self, parent, title, initial_list):
        super().__init__(parent)
        self.title(title)
        center_window(self, parent, 380, 420)
        self.result = None
        self.items = list(initial_list)
        self.transient(parent)

        tk.Label(self, text="请添加关键字 (同时满足 AND)：", anchor=tk.W, fg="#555").pack(fill=tk.X, padx=10,
                                                                                         pady=(10, 0))
        list_frame = tk.Frame(self)
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 5), pady=10)
        self.listbox = tk.Listbox(list_frame, font=("Microsoft YaHei", 10))
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for item in self.items: self.listbox.insert(tk.END, item)

        btn_frame = tk.Frame(self)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(5, 10), pady=10)
        ttk.Button(btn_frame, text="新建", command=self.add_item).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="删除", command=lambda: self.listbox.delete(tk.ANCHOR)).pack(fill=tk.X, pady=2)
        ttk.Separator(btn_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Button(btn_frame, text="确定", command=self.on_ok).pack(fill=tk.X, pady=2)
        self.grab_set()
        self.wait_window(self)

    def add_item(self):
        val = simpledialog.askstring("新建", "请输入关键字:", parent=self)
        if val and val.strip(): self.listbox.insert(tk.END, val.strip())

    def on_ok(self):
        self.result = list(self.listbox.get(0, tk.END))
        self.destroy()


class ImplantEntryDialog(tk.Toplevel):
    def __init__(self, parent, init_name="", init_model="全部", init_lv=0):
        super().__init__(parent)
        self.title("配置植入体规则")
        center_window(self, parent, 320, 240)
        self.result = None
        self.transient(parent)

        tk.Label(self, text="植入体名称:").grid(row=0, column=0, padx=10, pady=10, sticky=tk.E)
        self.name_entry = ttk.Entry(self, width=18)
        self.name_entry.insert(0, init_name)
        self.name_entry.grid(row=0, column=1, padx=10, pady=10, sticky=tk.W)

        tk.Label(self, text="要求型号:").grid(row=1, column=0, padx=10, pady=10, sticky=tk.E)
        self.model_combo = ttk.Combobox(self, values=["全部", "实验型", "基础型", "标准型", "进阶型"], state="readonly",
                                        width=15)
        self.model_combo.set(init_model)
        self.model_combo.grid(row=1, column=1, padx=10, pady=10, sticky=tk.W)

        tk.Label(self, text="最低等级:").grid(row=2, column=0, padx=10, pady=10, sticky=tk.E)
        self.lv_entry = ttk.Entry(self, width=18)
        self.lv_entry.insert(0, str(init_lv))
        self.lv_entry.grid(row=2, column=1, padx=10, pady=10, sticky=tk.W)

        btn_frame = tk.Frame(self)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=15)
        ttk.Button(btn_frame, text="保存", command=self.on_ok).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side=tk.LEFT, padx=10)
        self.grab_set()
        self.wait_window(self)

    def on_ok(self):
        try:
            lv = int(self.lv_entry.get())
        except:
            messagebox.showerror("错误", "等级必须为数字"); return
        self.result = {"name": self.name_entry.get().strip(), "model": self.model_combo.get(), "lv": lv}
        self.destroy()


class ImplantListEditDialog(tk.Toplevel):
    def __init__(self, parent, initial_list):
        super().__init__(parent)
        self.title("植入体规则集管理器")
        center_window(self, parent, 480, 420)
        self.result = None
        self.items = list(initial_list)
        self.transient(parent)

        tk.Label(self, text="需同时满足 (AND) 的植入体条件：", anchor=tk.W, fg="#555").pack(fill=tk.X, padx=10,
                                                                                           pady=(10, 0))
        list_frame = tk.Frame(self)
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 5), pady=10)
        self.listbox = tk.Listbox(list_frame, font=("Microsoft YaHei", 10))
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.refresh_listbox()

        btn_frame = tk.Frame(self)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(5, 10), pady=10)
        ttk.Button(btn_frame, text="新建规则", command=self.add_item).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="修改规则", command=self.edit_item).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="删除规则", command=self.delete_item).pack(fill=tk.X, pady=2)
        ttk.Separator(btn_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        ttk.Button(btn_frame, text="确定保存", command=self.on_ok).pack(fill=tk.X, pady=2)
        self.grab_set()
        self.wait_window(self)

    def refresh_listbox(self):
        self.listbox.delete(0, tk.END)
        for item in self.items:
            name = item['name'] if item['name'] else "(任意)"
            self.listbox.insert(tk.END, f"[{name}] | {item['model']} | Lv.{item['lv']}")

    def add_item(self):
        dialog = ImplantEntryDialog(self)
        if dialog.result: self.items.append(dialog.result); self.refresh_listbox()

    def edit_item(self):
        sel = self.listbox.curselection()
        if sel:
            idx = sel[0]
            dialog = ImplantEntryDialog(self, self.items[idx]['name'], self.items[idx]['model'], self.items[idx]['lv'])
            if dialog.result: self.items[idx] = dialog.result; self.refresh_listbox()

    def delete_item(self):
        sel = self.listbox.curselection()
        if sel: del self.items[sel[0]]; self.refresh_listbox()

    def on_ok(self):
        self.result = self.items
        self.destroy()


# ================= 主程序 =================

class EveSearchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("EVE 藏宝阁检索系统 V2.1 - by SakikoTogawa0214")
        self.root.geometry("1300x980")
        center_window(self.root, self.root, 1300, 980)

        self.all_data = {}
        self.filtered_data = {}
        self.filter_lists = {"skill": [], "global": [], "imp": []}

        self.load_data()
        self.build_ui()
        self.do_search()

    def load_data(self):
        try:
            if os.path.exists(DB_FILE):
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    self.all_data = json.load(f)
            else:
                self.all_data = {}
        except:
            self.all_data = {}

    def build_ui(self):
        # --- 筛选与控制区 ---
        filter_frame = tk.LabelFrame(self.root, text="🚀 筛选与控制面板", padx=10, pady=10)
        filter_frame.pack(fill=tk.X, padx=10, pady=5)

        # 统一配置列权重，确保拉伸均匀
        for i in range(6): filter_frame.columnconfigure(i, weight=1)
        filter_frame.columnconfigure(6, weight=0)  # 按钮列
        filter_frame.columnconfigure(7, weight=0)

        # --- 第一排：基础数值筛选 ---
        tk.Label(filter_frame, text="最高价格:").grid(row=0, column=0, sticky=tk.E)
        self.price_entry = ttk.Entry(filter_frame, width=12)
        self.price_entry.grid(row=0, column=1, sticky=tk.W)

        tk.Label(filter_frame, text="总技能点(万):").grid(row=0, column=2, sticky=tk.E)
        self.sp_entry = ttk.Entry(filter_frame, width=12)
        self.sp_entry.grid(row=0, column=3, sticky=tk.W)

        tk.Label(filter_frame, text="最低保险点:").grid(row=0, column=4, sticky=tk.E)
        self.ins_entry = ttk.Entry(filter_frame, width=12)
        self.ins_entry.grid(row=0, column=5, sticky=tk.W)

        # --- 第二排：点数进阶筛选 (洗点与自由点) ---
        tk.Label(filter_frame, text="最低洗点点数(万):").grid(row=1, column=0, sticky=tk.E)
        self.reset_sp_entry = ttk.Entry(filter_frame, width=12)
        self.reset_sp_entry.grid(row=1, column=1, sticky=tk.W)

        tk.Label(filter_frame, text="最低自由点数(万):").grid(row=1, column=2, sticky=tk.E)
        self.free_sp_entry = ttk.Entry(filter_frame, width=12)
        self.free_sp_entry.grid(row=1, column=3, sticky=tk.W)

        # --- 第三排：关键词配置 (技能与全局) ---
        ttk.Button(filter_frame, text="配置技能", width=8, command=lambda: self.edit_list("skill")).grid(row=2,
                                                                                                         column=0,
                                                                                                         pady=5)
        self.skill_show = ttk.Entry(filter_frame, state='readonly')
        self.skill_show.grid(row=2, column=1, columnspan=2, sticky="ew", padx=5)

        ttk.Button(filter_frame, text="全局包含", width=8, command=lambda: self.edit_list("global")).grid(row=2,
                                                                                                          column=3)
        self.global_show = ttk.Entry(filter_frame, state='readonly')
        self.global_show.grid(row=2, column=4, columnspan=2, sticky="ew", padx=5)

        # --- 第四排：植入体规则 (独占一行长条) ---
        ttk.Button(filter_frame, text="植入体规则", width=10, command=self.edit_implants).grid(row=3, column=0, pady=5)
        self.imp_show = ttk.Entry(filter_frame, state='readonly')
        self.imp_show.grid(row=3, column=1, columnspan=5, sticky="ew", padx=5)

        # --- 右侧固定按钮区 (跨多行显示) ---
        ttk.Button(filter_frame, text="🔍 立即检索", command=self.do_search).grid(row=0, column=6, rowspan=2, padx=10,
                                                                                 sticky="nsew")
        ttk.Button(filter_frame, text="🔄 重置", command=self.reset_filters).grid(row=2, column=6, rowspan=2, padx=10,
                                                                                 sticky="nsew")

        ttk.Button(filter_frame, text="🌐 检测环境", command=self.check_browser).grid(row=0, column=7, rowspan=2, padx=5,
                                                                                     sticky="nsew")
        ttk.Button(filter_frame, text="⚡ 开始爬取", command=self.start_crawl_task).grid(row=2, column=7, rowspan=2,
                                                                                        padx=5, sticky="nsew")

        # --- 数据面板 ---
        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.tree = ttk.Treeview(main_pane, columns=("id", "name", "price", "sp", "ins", "reset_sp", "free_sp"), show="headings")
        for col, head in zip(self.tree["columns"], ["编号", "角色昵称", "价格", "总技能点", "保险点", "洗点", "自由点"]):
            self.tree.heading(col, text=head)
        self.tree.column("id", width=80, anchor=tk.E)
        self.tree.column("name", width=150, anchor=tk.E)
        self.tree.column("price", width=80, anchor=tk.E)
        self.tree.column("sp", width=100, anchor=tk.E)
        self.tree.column("ins", width=100, anchor=tk.E)
        self.tree.column("reset_sp", width=80, anchor=tk.E)
        self.tree.column("free_sp", width=80, anchor=tk.E)
        main_pane.add(self.tree, weight=3)

        self.detail_text = tk.Text(main_pane, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 10))
        main_pane.add(self.detail_text, weight=2)

        # --- 日志显示 ---
        log_frame = tk.LabelFrame(self.root, text="实时运行状态", padx=5, pady=5)
        log_frame.pack(fill=tk.X, padx=10, pady=5)
        self.log_text = tk.Text(log_frame, height=10, font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
                                state=tk.DISABLED)
        self.log_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y);
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.tag_config("success", foreground="#a3d900")
        self.log_text.tag_config("error", foreground="#ff4b4b")
        self.log_text.tag_config("warning", foreground="#ffaa00")

        self.status_var = tk.StringVar()
        tk.Label(self.root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W).pack(side=tk.BOTTOM,
                                                                                                    fill=tk.X)

        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.on_double_click)

    # ================= 检索核心逻辑 =================

    def do_search(self):
        try:
            max_p = float(self.price_entry.get()) if self.price_entry.get() else float('inf')
            min_s = int(self.sp_entry.get()) * 10000 if self.sp_entry.get() else 0
            min_r = int(self.reset_sp_entry.get()) * 10000 if self.reset_sp_entry.get() else 0
            min_i = int(self.ins_entry.get()) if self.ins_entry.get() else 0
            min_f = int(self.free_sp_entry.get()) * 10000 if self.free_sp_entry.get() else 0
        except:
            messagebox.showwarning("错误", "数值项请输入数字"); return

        for item in self.tree.get_children(): self.tree.delete(item)
        self.filtered_data = {}
        self.load_data()

        for sn, acc in self.all_data.items():
            assets = acc.get("精简资产数据", {})
            basic_info = assets.get("人物", {}).get("基础信息", {})
            price = acc.get("价格", 0)

            # 技能/洗点/保险 解析 (还原 Version A)
            sp = int(str(basic_info.get("技能点", "0")).replace(',', ''))
            reset_sp = int(str(basic_info.get("洗点点数", "0")).replace(',', ''))
            free_sp = int(str(basic_info.get("自由技能点", "0")).replace(',', ''))
            ins = int(str(acc.get("精简资产数据", {}).get("货币", {}).get("保险点", "0")).replace(',', ''))

            if price > max_p or sp < min_s or reset_sp < min_r or free_sp < min_f or ins < min_i: continue

            # 过滤逻辑 (关键词、植入体等)
            if self.filter_lists["skill"]:
                s_str = json.dumps(assets.get("技能", {}), ensure_ascii=False).lower()
                if not all(k.lower() in s_str for k in self.filter_lists["skill"]): continue

            if self.filter_lists["global"]:
                a_str = json.dumps(acc, ensure_ascii=False).lower()
                if not all(k.lower() in a_str for k in self.filter_lists["global"]): continue

            if self.filter_lists["imp"]:
                implants = assets.get("人物", {}).get("植入体", [])
                match_all = True
                for rule in self.filter_lists["imp"]:
                    rule_met = False
                    for imp in implants:
                        lvl = int(imp.get("等级", 0))
                        full_name = imp.get("名称", "")
                        clean_name = re.sub(r'[\(（].*?[\)）]', '', full_name).strip().lower()
                        if lvl >= rule['lv'] and (rule['name'].lower() in clean_name) and (
                                rule['model'] == "全部" or rule['model'] in full_name):
                            rule_met = True;
                            break
                    if not rule_met: match_all = False; break
                if not match_all: continue

            self.filtered_data[sn] = acc
            self.tree.insert("", tk.END, iid=sn, values=(
                sn,
                acc.get("真实昵称"),
                f"¥{price}",
                f"{sp:,}",
                f"{ins:,}",
                f"{reset_sp:,}",
                f"{free_sp:,}"
            ))

        self.status_var.set(f" 总量: {len(self.all_data)} | 符合当前要求: {len(self.filtered_data)}")

    # ================= 爬虫与环境控制 =================

    def check_browser(self):
        try:
            requests.get("http://localhost:9222/json", timeout=1)
            messagebox.showinfo("就绪", "✅ Chrome 调试环境连接成功！")
        except:
            if messagebox.askyesno("未连接", "未检测到调试模式！\n请确认已安装Chrome\n是否立即启动Chrome？\n注：第一次启动时如果提示登录谷歌账号直接跳过"): self.launch_chrome()

    def launch_chrome(self):
        path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        if not os.path.exists(path): path = filedialog.askopenfilename(title="选择 Chrome.exe")
        if path:
            user_dir = os.path.abspath("./cbg_chrome_profile")
            cmd = f'"{path}" --remote-debugging-port=9222 --user-data-dir="{user_dir}" https://evem.cbg.163.com'
            subprocess.Popen(cmd, shell=True)

    def start_crawl_task(self):
        if not messagebox.askokcancel("确认", "请确认：\n1. 已完成藏宝阁账号登录\n2. Chrome浏览器窗口未关闭"): return
        ans = simpledialog.askstring("输入拉取次数", "拉取次数 (0=无限):", initialvalue="0")
        if ans is not None:
            threading.Thread(target=self._crawl_worker, args=(int(ans),), daemon=True).start()

    def _crawl_worker(self, max_s):
        old_stdout = sys.stdout
        sys.stdout = RedirectText(self.log_text)
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp("http://localhost:9222")
                page = browser.contexts[0].pages[0] if browser.contexts[0].pages else browser.contexts[0].new_page()
                print("🌐 引导浏览器跳转至商品列表...")
                page.goto("https://evem.cbg.163.com/cgi/mweb/pl", wait_until="domcontentloaded")
                time.sleep(1)
            scan.run_scan(max_s)
            self.root.after(0, self._on_complete)
        except Exception as e:
            print(f"❌ 运行异常: {e}")
        finally:
            sys.stdout = old_stdout

    def _on_complete(self):
        messagebox.showinfo("成功", "爬取任务已结束！");
        self.load_data();
        self.do_search()

    # ================= 辅助函数 =================

    def edit_list(self, key):
        dialog = SimpleListEditDialog(self.root, "配置关键字", self.filter_lists[key])
        if dialog.result is not None:
            self.filter_lists[key] = dialog.result
            target = self.skill_show if key == "skill" else self.global_show
            self.update_entry(target, " AND ".join(dialog.result))

    def edit_implants(self):
        dialog = ImplantListEditDialog(self.root, self.filter_lists["imp"])
        if dialog.result is not None:
            self.filter_lists["imp"] = dialog.result
            display = [f"{d['name']}(Lv{d['lv']})" for d in dialog.result]
            self.update_entry(self.imp_show, " AND ".join(display))

    def update_entry(self, widget, text):
        widget.config(state=tk.NORMAL);
        widget.delete(0, tk.END)
        widget.insert(0, text if text else "(无限制)");
        widget.config(state='readonly')

    def reset_filters(self):
        for e in [self.price_entry, self.sp_entry, self.ins_entry, self.reset_sp_entry]: e.delete(0, tk.END)
        self.filter_lists = {"skill": [], "global": [], "imp": []}
        for w in [self.skill_show, self.global_show, self.imp_show]: self.update_entry(w, "")
        self.do_search()

    def on_select(self, event):
        sel = self.tree.selection()
        if not sel: return
        acc = self.filtered_data[sel[0]]
        self.detail_text.config(state=tk.NORMAL);
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert(tk.END, json.dumps(acc, ensure_ascii=False, indent=4))
        for k_list in [self.filter_lists["skill"], self.filter_lists["global"]]:
            for kw in k_list: self.highlight(kw, "yellow")
        for rule in self.filter_lists["imp"]:
            if rule['name']: self.highlight(rule['name'], "lightblue")
        self.detail_text.config(state=tk.DISABLED)

    def highlight(self, kw, color):
        idx = "1.0"
        while True:
            idx = self.detail_text.search(kw, idx, nocase=True, stopindex=tk.END)
            if not idx: break
            end = f"{idx}+{len(kw)}c"
            tag = f"hl_{kw}_{color}";
            self.detail_text.tag_add(tag, idx, end)
            self.detail_text.tag_config(tag, background=color);
            idx = end

    def on_double_click(self, event):
        sel = self.tree.selection()
        if sel:
            link = self.filtered_data[sel[0]].get("藏宝阁链接")
            if link: webbrowser.open(link)


if __name__ == "__main__":
    root = tk.Tk()
    ttk.Style().theme_use("clam")
    EveSearchApp(root)
    root.mainloop()