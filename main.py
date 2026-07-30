from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.image import Image
from kivy.core.window import Window
from kivy.uix.gridlayout import GridLayout
import sqlite3
import barcode
from barcode.writer import ImageWriter
from io import BytesIO
from kivy.uix.camera import Camera
from pyzbar import pyzbar
from PIL import Image as PILImage
from datetime import datetime
import os
import csv

# ========== 安卓/桌面 路径自动适配 ==========
try:
    # 安卓打包环境导入
    from android.storage import app_storage_path
    ANDROID_ENV = True
except ImportError:
    ANDROID_ENV = False

if ANDROID_ENV:
    DB_NAME = os.path.join(app_storage_path(), "stock.db")
    EXPORT_CSV_PATH = os.path.join(app_storage_path(), "出库流水.csv")
else:
    DB_NAME = "stock.db"
    EXPORT_CSV_PATH = "出库流水.csv"

# ====================== 数据库初始化 ======================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS goods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        origin_code TEXT UNIQUE,
        cost_price REAL,
        sale_price REAL,
        new_code TEXT,
        stock_num INTEGER DEFAULT 0
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS out_record (
        rid INTEGER PRIMARY KEY AUTOINCREMENT,
        origin_code TEXT,
        out_count INTEGER,
        sell_price REAL,
        total_money REAL,
        out_time TEXT
    )''')
    conn.commit()
    conn.close()

def add_goods(origin_code, cost, sale, new_code, stock):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    try:
        cur.execute("""
        INSERT INTO goods(origin_code,cost_price,sale_price,new_code,stock_num)
        VALUES (?,?,?,?,?)""", (origin_code, float(cost), float(sale), new_code, int(stock)))
        conn.commit()
        return True
    except Exception as e:
        print(e)
        return False
    finally:
        conn.close()

def search_goods(code):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT * FROM goods WHERE origin_code=? OR new_code=?", (code, code))
    res = cur.fetchone()
    conn.close()
    return res

def out_stock_with_price(code, out_num, real_sell_price):
    goods = search_goods(code)
    if not goods:
        return False, "商品不存在"
    gid, origin, cost, sale, newcode, stock = goods
    if stock < out_num:
        return False, f"库存不足，当前库存：{stock}"

    total = round(out_num * real_sell_price, 2)
    now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE goods SET stock_num = stock_num - ? WHERE id=?", (out_num, gid))
    cur.execute("""INSERT INTO out_record(origin_code,out_count,sell_price,total_money,out_time)
        VALUES (?,?,?,?,?)""", (origin, out_num, real_sell_price, total, now_time))
    conn.commit()
    conn.close()
    return True, f"出库成功！成交总价：{total} 元"

def delete_goods(code):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM goods WHERE origin_code=? OR new_code=?", (code, code))
    conn.commit()
    row = cur.rowcount
    conn.close()
    return row > 0

def get_out_record_by_code(code):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT * FROM out_record WHERE origin_code=? ORDER BY rid DESC", (code,))
    data = cur.fetchall()
    conn.close()
    return data

def get_all_out_records():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT * FROM out_record ORDER BY rid DESC")
    records = cur.fetchall()
    conn.close()
    all_data = []
    for rec in records:
        rid, ori_code, cnt, sell_price, total_sale, out_time = rec
        goods = search_goods(ori_code)
        cost = goods[2] if goods else 0
        total_cost = round(cnt * cost, 2)
        profit = round(total_sale - total_cost, 2)
        all_data.append([ori_code, cnt, sell_price, total_sale, cost, total_cost, profit, out_time])
    return all_data

def export_all_out_csv():
    records = get_all_out_records()
    save_path = EXPORT_CSV_PATH
    header = ["商品条码","出库数量","本次售价","总销售额","单品成本","总成本","单笔利润","出库时间"]
    try:
        with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(records)
        return True, f"导出成功！文件路径：{save_path}"
    except Exception as e:
        print(e)
        return False, f"导出失败：{str(e)}"

# ====================== 主界面布局 ======================
class StockLayout(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.spacing = 6
        self.padding = 10
        Window.size = (360, 640)
        self.current_goods = None

        self.camera = Camera(play=True, resolution=(640,480))
        self.camera.size_hint_y = 0.32
        self.add_widget(self.camera)

        form = GridLayout(cols=2, spacing=4, size_hint_y=0.32)
        form.add_widget(Label(text="原始条码:"))
        self.origin_input = TextInput(hint_text="扫码自动填充", size_hint_x=0.6)
        form.add_widget(self.origin_input)

        form.add_widget(Label(text="成本价:"))
        self.cost_input = TextInput(hint_text="例如：12.5", input_filter="float", size_hint_x=0.6)
        form.add_widget(self.cost_input)

        form.add_widget(Label(text="预设销售价:"))
        self.sale_input = TextInput(hint_text="例如：19.9", input_filter="float", size_hint_x=0.6)
        form.add_widget(self.sale_input)

        form.add_widget(Label(text="初始库存:"))
        self.stock_input = TextInput(hint_text="数字", input_filter="int", size_hint_x=0.6)
        form.add_widget(self.stock_input)
        self.add_widget(form)

        btn_row1 = BoxLayout(spacing=4, size_hint_y=0.08)
        btn_row1.add_widget(Button(text="识别条码", on_press=self.scan_code))
        btn_row1.add_widget(Button(text="入库保存", on_press=self.save_stock))
        btn_row1.add_widget(Button(text="查询商品", on_press=self.query_by_code))
        self.add_widget(btn_row1)

        btn_row2 = BoxLayout(spacing=4, size_hint_y=0.08)
        btn_row2.add_widget(Button(text="商品出库", on_press=self.open_out_popup))
        btn_row2.add_widget(Button(text="出库记录", on_press=self.show_out_log))
        btn_row2.add_widget(Button(text="导出全部流水", on_press=self.export_csv_all))
        btn_row2.add_widget(Button(text="删除商品", on_press=self.delete_item))
        btn_row2.add_widget(Button(text="清空输入框", on_press=self.clear_input))
        self.add_widget(btn_row2)

        self.info_label = Label(text="商品信息区域\n扫码查询商品", size_hint_y=0.18)
        self.add_widget(self.info_label)

        self.barcode_img = Image(size_hint_y=0.22)
        self.add_widget(self.barcode_img)

    def scan_code(self, instance):
        texture = self.camera.texture
        if not texture:
            return
        buf = texture.pixels
        img = PILImage.frombytes("RGBA", texture.size, buf)
        barcodes = pyzbar.decode(img)
        if barcodes:
            code_text = barcodes[0].data.decode("utf-8")
            self.origin_input.text = code_text
            self.show_msg(f"识别成功：{code_text}")
        else:
            self.show_msg("未识别条码，请调整距离")

    def generate_new_barcode(self, origin_code):
        new_code_str = f"NEW_{origin_code}"
        CODE128 = barcode.get_barcode_class('code128')
        barcode_writer = CODE128(new_code_str, writer=ImageWriter())
        buffer = BytesIO()
        barcode_writer.write(buffer, options={"write_text": True})
        buffer.seek(0)
        return new_code_str, buffer

    def save_stock(self, instance):
        origin_code = self.origin_input.text.strip()
        cost = self.cost_input.text.strip()
        sale = self.sale_input.text.strip()
        stock = self.stock_input.text.strip()
        if not all([origin_code, cost, sale, stock]):
            self.show_msg("原始条码、成本价、预设销售价、初始库存不能为空！")
            return
        new_code, img_buffer = self.generate_new_barcode(origin_code)
        ok = add_goods(origin_code, cost, sale, new_code, int(stock))
        if ok:
            self.show_msg(f"入库成功！自定义条码：{new_code}")
            self.barcode_img.source = img_buffer
        else:
            self.show_msg("入库失败！该原始条码已存在")

    def query_by_code(self, instance):
        code = self.origin_input.text.strip()
        if not code:
            self.show_msg("请扫描或输入条码")
            return
        data = search_goods(code)
        self.current_goods = data
        if data:
            gid, origin, cost, sale, newcode, stock = data
            info_text = f"""【商品信息】
原始条码：{origin}
自定义条码：{newcode}
成本价：{cost} 元
档案预设售价：{sale} 元
当前库存：{stock} 件
💡出库时可单独修改本次售价，自动计算单笔利润"""
            self.info_label.text = info_text
        else:
            self.info_label.text = "⚠️未找到该商品！"

    def open_out_popup(self, instance):
        code = self.origin_input.text.strip()
        if not code:
            self.show_msg("先扫描/输入商品条码！")
            return
        goods_info = search_goods(code)
        if not goods_info:
            self.show_msg("无此商品信息！")
            return
        _, _, _, default_price, _, _ = goods_info

        content = GridLayout(cols=2, spacing=8, padding=10)
        content.add_widget(Label(text="出库数量："))
        out_input = TextInput(hint_text="填写数量", input_filter="int")
        content.add_widget(out_input)

        content.add_widget(Label(text="本次销售单价："))
        price_input = TextInput(hint_text="可修改", input_filter="float", text=str(default_price))
        content.add_widget(price_input)

        def confirm_out(x):
            num = out_input.text.strip()
            sell_price = price_input.text.strip()
            if not num or int(num) <= 0:
                self.show_msg("请输入有效的出库数量")
                return
            if not sell_price or float(sell_price) <= 0:
                self.show_msg("售价必须大于0")
                return
            res, msg = out_stock_with_price(code, int(num), float(sell_price))
            self.show_msg(msg)
            popup.dismiss()
            self.query_by_code(None)

        popup = Popup(title="商品出库", content=content, size_hint=(0.88,0.42))
        btn_box = BoxLayout(spacing=10,padding=5)
        btn_ok = Button(text="确认出库", on_press=confirm_out)
        btn_cancel = Button(text="取消", on_press=lambda x: popup.dismiss())
        btn_box.add_widget(btn_ok)
        btn_box.add_widget(btn_cancel)
        content.add_widget(btn_box)
        popup.open()

    def show_out_log(self, instance):
        code = self.origin_input.text.strip()
        if not code:
            self.show_msg("请先输入商品条码")
            return
        records = get_out_record_by_code(code)
        text = f"【条码 {code} 出库记录（含利润）】\n"
        if len(records) == 0:
            text += "暂无出库流水"
        else:
            for item in records:
                rid, ori_code, cnt, price, total, t = item
                goods = search_goods(ori_code)
                cost = goods[2]
                profit = round(total - cnt * cost, 2)
                text += f"时间:{t}\n数量:{cnt} | 售价:{price} | 销售额:{total} | 利润:{profit}\n\n"
        popup = Popup(title="出库流水", content=Label(text=text), size_hint=(0.9,0.7))
        popup.open()

    def export_csv_all(self, instance):
        ok, msg = export_all_out_csv()
        self.show_msg(msg)

    def delete_item(self, instance):
        code = self.origin_input.text.strip()
        if not code:
            self.show_msg("请输入条码！")
            return
        confirm_pop = Popup(title="确认删除", content=Label(text="删除商品档案，出库流水仍然保留！"), size_hint=(0.8,0.3))
        def do_del(x):
            suc = delete_goods(code)
            if suc:
                self.show_msg("商品档案删除成功")
                self.clear_input(None)
            else:
                self.show_msg("删除失败，无此商品")
            confirm_pop.dismiss()
        box = BoxLayout()
        box.add_widget(Button(text="确认删除", on_press=do_del))
        box.add_widget(Button(text="取消", on_press=lambda a: confirm_pop.dismiss()))
        confirm_pop.content = box
        confirm_pop.open()

    def clear_input(self, instance):
        self.origin_input.text = ""
        self.cost_input.text = ""
        self.sale_input.text = ""
        self.stock_input.text = ""
        self.info_label.text = "商品信息区域\n扫码查询商品"
        self.barcode_img.source = ""
        self.current_goods = None

    def show_msg(self, text):
        popup = Popup(title="提示", content=Label(text=text), size_hint=(0.8,0.3))
        popup.open()

class StockApp(App):
    def build(self):
        init_db()
        self.title = "条码进销存入库系统V4.0"
        return StockLayout()

if __name__ == "__main__":
    StockApp().run()