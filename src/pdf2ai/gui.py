"""Small Tk desktop interface; conversion runs off the UI thread."""
import queue
import threading
from pathlib import Path
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError as exc:
    raise SystemExit("GUIにはTkinterが必要です。READMEのインストール手順を確認してください。CLI版はTkinterなしで使用できます。") from exc
from .native import convert


def main():
    root = tk.Tk()
    root.title("PDF → Illustrator 2020")
    root.geometry("700x500")
    files = []
    messages = queue.Queue()
    folder = tk.StringVar()
    page = tk.StringVar(value="")
    outline = tk.BooleanVar(value=False)
    strict = tk.BooleanVar(value=False)
    frame = ttk.Frame(root, padding=14);frame.pack(fill="both",expand=True)
    ttk.Label(frame,text="PDF → Illustrator 2020（実験的な変換）").pack(anchor="w")
    ttk.Label(frame,text="対応：パス・特色・画像・グラデーション・描画モード・切り抜き・配置PDF。未対応の機能は自動で画像化して取り込みます。",wraplength=660).pack(anchor="w",pady=8)
    listing = tk.Listbox(frame,height=6);listing.pack(fill="x")

    def choose():
        selected = filedialog.askopenfilenames(filetypes=[("PDF", "*.pdf")])
        if selected:
            files[:] = [Path(p) for p in selected]
            listing.delete(0,"end")
            for p in files: listing.insert("end",str(p))
            if not folder.get(): folder.set(str(files[0].parent))

    pick = ttk.Button(frame,text="PDFを選択",command=choose);pick.pack(anchor="w",pady=6)
    row = ttk.Frame(frame);row.pack(fill="x")
    ttk.Label(row,text="出力先").pack(side="left")
    ttk.Entry(row,textvariable=folder).pack(side="left",fill="x",expand=True,padx=8)
    def choose_folder():
        selected = filedialog.askdirectory()
        if selected:folder.set(selected)
    ttk.Button(row,text="選択",command=choose_folder).pack(side="left")
    row = ttk.Frame(frame);row.pack(fill="x",pady=8)
    ttk.Label(row,text="対象ページ（複数ページPDFの場合、1から指定）").pack(side="left")
    ttk.Entry(row,textvariable=page,width=6).pack(side="left",padx=8)
    ttk.Checkbutton(frame,text="Ghostscriptで前処理する（補助的な文字アウトライン化）",variable=outline).pack(anchor="w",pady=4)
    ttk.Checkbutton(frame,text="未対応機能を画像化せずエラーにする",variable=strict).pack(anchor="w",pady=4)
    log = tk.Text(frame,height=8,state="disabled");log.pack(fill="both",expand=True)

    def write(text):
        log.configure(state="normal");log.insert("end",text+"\n");log.see("end");log.configure(state="disabled")

    def run():
        if not files or not Path(folder.get()).is_dir():
            messagebox.showerror("入力の確認","PDFと出力先ディレクトリを選択してください。");return
        try:
            number = int(page.get()) if page.get().strip() else None
            if number is not None and number<1:raise ValueError()
        except ValueError:
            messagebox.showerror("ページ番号","1以上の整数を指定してください。");return
        outline_selected = outline.get()
        strict_selected = strict.get()
        selected = list(files);directory = Path(folder.get())
        start.configure(state="disabled");pick.configure(state="disabled")
        def work():
            for p in selected:
                try:
                    out = directory/(p.stem+".ai")
                    report = convert(p,out,page_number=number,outline_text=outline_selected,raster_fallback=not strict_selected)
                    if report["rasterized"]: messages.put(f"画像化して保存（300dpi）: {report['fallback_reason']}")
                    messages.put(f"保存: {out}（特色{len(report['spots'])}色）")
                except Exception as error:
                    messages.put(f"エラー: {p.name}: {error}")
            messages.put(None)
        threading.Thread(target=work,daemon=True).start()

    start = ttk.Button(frame,text="変換",command=run);start.pack(anchor="e",pady=8)
    def poll():
        try:
            while True:
                message = messages.get_nowait()
                if message is None:
                    start.configure(state="normal");pick.configure(state="normal")
                else:write(message)
        except queue.Empty:pass
        root.after(100,poll)
    poll();root.mainloop()


if __name__ == "__main__":main()
