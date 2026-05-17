import time
import json
import os
import requests
import re
from playwright.sync_api import sync_playwright

# --- 配置区 ---
DB_FILE = "eve_full_data.json"
DETAIL_API_PATH = "get_equip_detail"
MAX_SCROLLS = 0  # 0: 无限滚动直到到底。 >0: 最大滚动次数限制 (例如设为 10 就是最多滚 10 次)
MAX_SCROLLS_N = 0
MAX_IDLE_SCROLLS = 3  # 连续几次没有扫到新号就判定为到底并停止


def clean_html(html_str):

    if not html_str: return ""
    tmp = re.sub(r'<br\s*/?>', '\n', html_str)
    clean_text = re.sub(r'<[^>]+>', '', tmp)
    return clean_text.replace('&nbsp;', ' ').strip()


def extract_count(item):

    if "sub_icons" in item and item["sub_icons"]:
        html = item["sub_icons"][0].get("html", "")
        # 正则匹配 <div>数字</div>
        match = re.search(r'>\s*([\d,]+)\s*<', html)
        if match:
            return int(match.group(1).replace(',', ''))
    return 1


def parse_nanocore(contents, target_dict):

    for c in contents:
        c_type = c.get("type")
        if c_type == "title":
            t_text = c.get("content", "")
            if "当前装配" in t_text:
                target_dict["当前装配"] = t_text.replace("当前装配纳米核心：", "").replace("当前装配：", "").strip()
        elif c_type == "kv-list":
            for kv in c.get("contents", []):
                lbl = kv.get("label", kv.get("lable", ""))  # 兼容网易错别字
                val = kv.get("value", "")
                if lbl and val:
                    target_dict["属性"][lbl] = val
        elif c_type == "icon-list":
            for item in c.get("contents", []):
                lbl = item.get("label", item.get("lable", ""))
                if lbl:
                    target_dict["库存"][lbl] = target_dict["库存"].get(lbl, 0) + extract_count(item)


def fetch_static_assets(game_ordersn):

    try:
        url = f"https://cbg-other-desc.res.netease.com/evem/static/equipdesc/{game_ordersn}.json"
        res = requests.get(url, timeout=5)
        if res.status_code != 200: return None

        raw_data = res.json()
        raw_desc = raw_data.get("equip_desc", "{}")
        display_content = json.loads(raw_desc).get("display_content", [])


        clean_data = {
            "人物": {"基础信息": {}, "认知神经科学": {}, "植入体": []},
            "技能": {},
            "货币": {},
            "资产": {}
        }

        for tab in display_content:
            t_name = tab.get("tab_name", "")

            # ================= 解析【人物】页签 =================
            if t_name == "人物":
                cur_sec = ""
                skip_sec = False

                for content in tab.get("contents", []):
                    c_type = content.get("type")
                    if c_type == "title":
                        cur_sec = content.get("content", "")
                        skip_sec = "雇佣" in cur_sec  # 拦截雇佣记录
                        continue

                    if skip_sec or c_type != "kv-list":
                        continue

                    kv_items = content.get("contents", [])

                    if "基础信息" in cur_sec:
                        for kv in kv_items:
                            lbl, val = kv.get("label", kv.get("lable", "")), kv.get("value")
                            if lbl not in ["名称"] and "到期" not in lbl:
                                clean_data["人物"]["基础信息"][lbl] = val

                    elif "认知神经科学" in cur_sec:
                        for kv in kv_items:
                            lbl = kv.get("label", kv.get("lable", ""))
                            clean_data["人物"]["认知神经科学"][lbl] = kv.get("value")

                    elif "植入体" in cur_sec:
                        implant_cache = {}
                        for kv in kv_items:
                            lbl = kv.get("label", kv.get("lable", ""))
                            val, html = kv.get("value"), kv.get("html", "")
                            if "等级" in lbl:
                                if implant_cache:
                                    clean_data["人物"]["植入体"].append(implant_cache)
                                implant_cache = {"名称": lbl.replace(" 等级", ""), "等级": val, "通用元件": "无"}
                            elif "通用元件" in lbl:
                                implant_cache["通用元件"] = clean_html(html) or "无"
                        if implant_cache:
                            clean_data["人物"]["植入体"].append(implant_cache)

            # ================= 解析【技能】页签 =================
            # 🌟 这里修复了缩进错误，与 t_name == "人物" 保持同级
            elif t_name == "技能":
                for content in tab.get("contents", []):
                    # --- 处理新的 tag-list 结构 (总技能点、自由点、洗点) ---
                    if content.get("type") == "tag-list":
                        for tag in content.get("contents", []):
                            text = tag.get("content", "")

                            # 提取数字的通用正则
                            num_match = re.search(r'\d+', text)
                            if not num_match:
                                continue
                            val = num_match.group()

                            if "技能总数" in text:
                                clean_data["人物"]["基础信息"]["技能点"] = val
                            elif "自由技能点" in text:
                                clean_data["人物"]["基础信息"]["自由技能点"] = val
                            elif "技能重置载体" in text or "重置载体" in text:
                                clean_data["人物"]["基础信息"]["洗点点数"] = val

                    # --- 处理旧的 kv-list 结构（兼容老数据）---
                    elif content.get("type") == "kv-list":
                        for kv in content.get("contents", []):
                            lbl = kv.get("label", kv.get("lable", ""))
                            val = kv.get("value")
                            if lbl and val:
                                if "技能总数" in lbl:
                                    clean_data["人物"]["基础信息"]["技能点"] = val
                                elif "自由技能点" in lbl:
                                    clean_data["人物"]["基础信息"]["自由技能点"] = val
                                elif "重置载体" in lbl:
                                    clean_data["人物"]["基础信息"]["洗点点数"] = val

                    # --- 原有的详细技能列表解析 ---
                    if content.get("type") == "icon-list":
                        for group in content.get("contents", []):
                            try:
                                g_name = group["contents"][0]["content"]
                                sks = []
                                for pop in group.get("pop-page", {}).get("contents", []):
                                    if pop.get("type") == "kv-list":
                                        for sk in pop.get("contents", []):
                                            if sk.get("value") and sk.get("value") != "无":
                                                sks.append(sk.get("value"))
                                if sks: clean_data["技能"][g_name] = sks
                            except:
                                continue

            # ================= 解析【货币】页签 =================
            elif t_name == "货币" or (t_name == "资产" and not clean_data["货币"]):
                for content in tab.get("contents", []):
                    if content.get("type") == "kv-list":
                        for kv in content.get("contents", []):
                            lbl = kv.get("label", kv.get("lable", ""))
                            clean_data["货币"][lbl] = kv.get("value")


            elif t_name == "纳米核心":
                clean_data["资产"].setdefault("纳米核心", {"当前装配": "无", "属性": {}, "库存": {}})
                parse_nanocore(tab.get("contents", []), clean_data["资产"]["纳米核心"])

            # ================= 解析【资产】页签 =================
            elif t_name == "资产":
                for content in tab.get("contents", []):
                    if content.get("type") == "tabs":
                        for sub_tab in content.get("contents", []):
                            sub_n = sub_tab.get("tab_name", "未知类别")

                            # 1. 处理涂装 (直接用列表)
                            if sub_n == "涂装":
                                clean_data["资产"].setdefault(sub_n, [])
                                for sub_c in sub_tab.get("contents", []):
                                    if sub_c.get("type") == "icon-list":
                                        for item in sub_c.get("contents", []):
                                            lbl = item.get("label", item.get("lable", ""))
                                            if lbl: clean_data["资产"][sub_n].append(lbl)

                            # 2. 处理纳米核心 (放在资产平级)
                            elif sub_n == "纳米核心":
                                clean_data["资产"].setdefault(sub_n, {"当前装配": "无", "属性": {}})
                                parse_nanocore(sub_tab.get("contents", []), clean_data["资产"][sub_n])

                            # 3. 处理仓库、装配及其他
                            else:
                                clean_data["资产"].setdefault(sub_n, {})
                                category = "默认分类"

                                for sub_c in sub_tab.get("contents", []):
                                    if sub_c.get("type") == "text" and sub_c.get("content") not in ["无", ""]:
                                        category = sub_c.get("content")

                                    elif sub_c.get("type") == "icon-list":
                                        # 【防爆破核心点】: 无论如何，强制确保 category 字典已被初始化
                                        clean_data["资产"][sub_n].setdefault(category, {})
                                        target_dict = clean_data["资产"][sub_n][category]

                                        for item in sub_c.get("contents", []):
                                            label = item.get("label", item.get("lable", ""))
                                            if not label: continue
                                            target_dict[label] = target_dict.get(label, 0) + extract_count(item)

        # ================= 数据收尾：清理空节点 =================
        # 防止页面中虽然存在该页签，但没有任何物品，导致的冗余空字典
        for k in list(clean_data["资产"].keys()):
            # 纳米核心如果全为空则清理
            if k == "纳米核心":
                nano = clean_data["资产"][k]
                if nano["当前装配"] == "无" and not nano["属性"] and not nano.get("库存"):
                    del clean_data["资产"][k]
            # 普通字典或列表为空则清理
            elif not clean_data["资产"][k]:
                del clean_data["资产"][k]
            # 清理仓库、装配中空的默认分类
            elif isinstance(clean_data["资产"][k], dict):
                for sub_k in list(clean_data["资产"][k].keys()):
                    if not clean_data["资产"][k][sub_k]:
                        del clean_data["资产"][k][sub_k]
                if not clean_data["资产"][k]:
                    del clean_data["资产"][k]

        return {"精简资产数据": clean_data}

    except Exception as e:
        print(f"解析失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def run_scan(max_scrolls_param=0):
    # ==========================================
    # 1. 启动时的控制台交互
    # ==========================================
    global MAX_SCROLLS_N
    MAX_SCROLLS_N = max_scrolls_param
    print("=" * 45)
    print("🚀 欢迎使用 EVE 藏宝阁数据抓取系统 🚀")
    print("=" * 45)

    try:
        global MAX_SCROLLS
        MAX_SCROLLS = int(MAX_SCROLLS_N) if MAX_SCROLLS_N else 0
    except ValueError:
        print("⚠️ 输入包含非数字，自动切换为默认的 [无限探底模式] (0)。")
        MAX_SCROLLS = 0

    MAX_IDLE_SCROLLS = 3  # 连续未扫到新号的判定阈值

    if MAX_SCROLLS == 0:
        print("💡 当前模式：[无限探底]，直到连续 3 次没扫到新账号才会停止。")
    else:
        print(f"💡 当前模式：[固定深度]，最多只滚动 {MAX_SCROLLS} 次。")
    print("-" * 45)

    # ==========================================
    # 2. 读取本地数据库
    # ==========================================
    if os.path.exists(DB_FILE) and os.path.getsize(DB_FILE) > 0:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            character_db = json.load(f)
    else:
        character_db = {}

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]

            list_page = next((p for p in context.pages if "cbg.163.com" in p.url), None)
            if not list_page:
                print("❌ 错误：请在浏览器中打开藏宝阁页面。")
                return

            print("📄 正在开启独立的数据抓取副核...")
            detail_page = context.new_page()

            session_seen_sns = set()  # 记录本次运行中网页真实请求到的所有账号
            pending_sns = []  # 记录等待去采集详情的全新账号

            def on_list(res):
                if ("recommend.py" in res.url or "search.py" in res.url) and res.status == 200:
                    try:
                        items = res.json().get("result", [])
                        for i in items:
                            sn = i.get("game_ordersn")
                            if sn:
                                session_seen_sns.add(sn)
                                if sn not in character_db and sn not in pending_sns:
                                    pending_sns.append(sn)
                    except:
                        pass

            list_page.on("response", on_list)
            print("🚀 系统初始化完毕，开始智能扫描...")

            list_page.reload(wait_until="networkidle")
            time.sleep(2)

            # ==========================================
            # 3. 边滚边抓主循环
            # ==========================================
            scroll_count = 0
            idle_count = 0

            while True:
                if MAX_SCROLLS > 0 and scroll_count >= MAX_SCROLLS:
                    print(f"\n⏹️ 达到你设定的最大滚动次数 ({MAX_SCROLLS})，终止探测。")
                    break

                scroll_count += 1
                if MAX_SCROLLS > 0:
                    print(f"\n--- 滚动扫描层级: {scroll_count}/{MAX_SCROLLS} ---")
                else:
                    print(f"\n--- 滚动扫描层级: {scroll_count} (无限探底中...) ---")

                # 记录滑动前的探测总数
                start_seen_count = len(session_seen_sns)

                # 触发页面滚动
                list_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(3.0)

                # 记录滑动后的探测总数
                end_seen_count = len(session_seen_sns)


                current_batch = pending_sns[:]
                pending_sns.clear()


                if end_seen_count > start_seen_count or len(current_batch) > 0:
                    idle_count = 0  # 闲置计数器清零
                    print(f"   ✅ 网页维持活跃加载状态，当前已累计嗅探: {end_seen_count} 个")

                    if len(current_batch) > 0:
                        print(f"   ⏳ 过滤掉已存老号，开始并行采集 {len(current_batch)} 个新号详情...")
                        for idx, sn in enumerate(current_batch):
                            print(f"   🔍 [{idx + 1}/{len(current_batch)}] 采集: {sn}...", end="", flush=True)
                            try:
                                with detail_page.expect_response(lambda r: DETAIL_API_PATH in r.url and r.status == 200,
                                                                 timeout=10000) as resp:
                                    detail_page.goto(f"https://evem.cbg.163.com/cgi/mweb/equip/1/{sn}",
                                                     wait_until="domcontentloaded")
                                    api_json = resp.value.json()

                                    if api_json.get("status") == 1:
                                        equip = api_json["equip"]


                                        data = {
                                            "真实昵称": equip.get("equip_name"),
                                            "价格": float(equip.get("price", 0)) / 100,
                                            "AUR": "0", "PLEX": "0", "服务器": equip.get("server_name"),
                                            "藏宝阁链接": f"https://evem.cbg.163.com/cgi/mweb/equip/1/{sn}",
                                            "抓取时间": time.strftime("%Y-%m-%d %H:%M:%S")
                                        }

                                        for attr in equip.get("other_info", {}).get("basic_attrs", []):
                                            if attr[0] == "AUR": data["AUR"] = attr[1]
                                            if attr[0] == "PLEX": data["PLEX"] = attr[1]

                                        full_assets = fetch_static_assets(sn)
                                        if full_assets: data.update(full_assets)

                                        character_db[sn] = data
                                        with open(DB_FILE, "w", encoding="utf-8") as f:
                                            json.dump(character_db, f, ensure_ascii=False, indent=4)
                                        print(f" -> ✅ [{data['真实昵称']}] 存盘成功")
                                    else:
                                        print(" -> 🟡 接口异常")
                            except Exception as e:
                                print(f" -> ❌ 抓取失败 (超时或报错)")

                            time.sleep(1.0)
                    else:
                        print(f"   ⏩ 本轮刷出的数据全是本地已有的老号，跳过详情采集，继续加速下探...")
                else:
                    idle_count += 1
                    print(f"   ⚠️ 第 {idle_count} 次未刷出新列表，页面可能已到底部...")

                # 智能刹车判断
                if idle_count >= MAX_IDLE_SCROLLS:
                    print(f"\n🛑 连续 {MAX_IDLE_SCROLLS} 次滚动都没有任何数据响应，判定已彻底爬完该列表，安全刹车！")
                    break

            list_page.remove_listener("response", on_list)
            print("\n正在安全关闭连接...")
            detail_page.close()
            context.close()
            browser.close()

        except Exception as e:
            print(f"🔴 全局运行错误: {e}")

    print(f"\n✨ 任务结束。目前本地库总账号数: {len(character_db)}")

if __name__ == "__main__":
    run_scan(0)