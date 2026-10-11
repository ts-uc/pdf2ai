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
from .vector import ConversionError
from .multiboard import convert_document
from .cli import select_pages, publish_report
import pikepdf


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
    combine = tk.BooleanVar(value=False)
    report_selected = tk.BooleanVar(value=False)
    dpi = tk.StringVar(value='300')
    cancelled = threading.Event()
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
    ttk.Label(row,text="対象ページ（all / 1,3-5。空欄は単ページ）").pack(side="left")
    ttk.Entry(row,textvariable=page,width=6).pack(side="left",padx=8)
    ttk.Checkbutton(frame,text="Ghostscriptで前処理する（補助的な文字アウトライン化）",variable=outline).pack(anchor="w",pady=4)
    ttk.Checkbutton(frame,text="未対応機能を画像化せずエラーにする",variable=strict).pack(anchor="w",pady=4)
    ttk.Checkbutton(frame,text='選択ページを1つのAIにまとめる',variable=combine).pack(anchor='w')
    ttk.Checkbutton(frame,text='JSONレポートを保存する',variable=report_selected).pack(anchor='w')
    row = ttk.Frame(frame);row.pack(fill='x')
    ttk.Label(row,text='画像化解像度（72〜1200dpi）').pack(side='left')
    ttk.Entry(row,textvariable=dpi,width=8).pack(side='left')
    log = tk.Text(frame,height=8,state="disabled");log.pack(fill="both",expand=True)

    def write(text):
        log.configure(state="normal");log.insert("end",text+"\n");log.see("end");log.configure(state="disabled")

    def run():
        if not files or not Path(folder.get()).is_dir():
            messagebox.showerror("入力の確認","PDFと出力先ディレクトリを選択してください。");return
        try:
            resolution = float(dpi.get())
            if not 72 <= resolution <= 1200: raise ValueError()
            expression = page.get().strip()
            combined = combine.get()
            if combined and outline.get():
                messagebox.showerror('入力の確認','結合とGhostscript前処理は現在併用できません。');return
            selected = list(files);directory = Path(folder.get())
            plans = []
            for source in selected:
                with pikepdf.open(source) as pdf:
                    if not expression and not combined and len(pdf.pages) != 1:
                        raise ConversionError('複数ページPDFの対象ページを指定してください')
                    numbers = select_pages(expression or 'all', len(pdf.pages))
                if combined:
                    plans.append((source, directory/(source.stem+'.ai'), numbers))
                else:
                    plans.extend((source, directory/(source.stem+(f'_{number:03d}' if len(numbers)>1 else '')+'.ai'), number) for number in numbers)
            outputs = [out.resolve() for _,out,_ in plans]
            if len(outputs) != len(set(outputs)):
                raise ConversionError('入力ファイルの出力名が衝突しています')
        except (ValueError, OSError, pikepdf.PdfError) as error:
            messagebox.showerror('入力の確認',str(error));return
        outline_selected = outline.get()
        strict_selected = strict.get()
        write_report = report_selected.get()
        report_path = directory/'pdf2ai.report.json'
        if write_report and report_path.resolve() in {p.resolve() for p in selected} | set(outputs):
            messagebox.showerror('入力の確認','レポートの保存先が入力または出力と衝突しています。');return
        existing = [out for _,out,_ in plans if out.exists()]
        if write_report and report_path.exists(): existing.append(report_path)
        overwrite = bool(existing)
        if existing and not messagebox.askyesno('上書き確認',f'{len(existing)}件の既存ファイルを上書きしますか？'):return
        cancelled.clear()
        start.configure(state="disabled");pick.configure(state="disabled")
        def work():
            reports = []
            for p, out, selection in plans:
                if cancelled.is_set():
                    messages.put('キャンセルしました。完了済みのファイルは保持します。');break
                try:
                    if combined:
                        batch = convert_document(p,out,pages=selection,overwrite=overwrite,
                                                 raster_fallback=not strict_selected,raster_dpi=resolution)
                    else:
                        batch = [convert(p,out,page_number=selection,overwrite=overwrite,outline_text=outline_selected,
                                         raster_fallback=not strict_selected,raster_dpi=resolution)]
                    reports.extend(batch)
                    report = batch[0]
                    for item in batch:
                        if item['rasterized']: messages.put(f"画像化して保存（{resolution:g}dpi）: page {item['page']}: {item['fallback_reason']}")
                    messages.put(f"保存: {out}（特色{len(report['spots'])}色）")
                except Exception as error:
                    reports.append({'input':str(p),'output':str(out),'error':str(error)})
                    messages.put(f"エラー: {p.name}: {error}")
            if write_report:
                try: publish_report(report_path, reports)
                except OSError as error: messages.put(f'レポート保存エラー: {error}')
            messages.put(None)
        threading.Thread(target=work,daemon=True).start()

    start = ttk.Button(frame,text="変換",command=run);start.pack(anchor="e",pady=8)
    ttk.Button(frame,text='次のファイル／ページからキャンセル',command=cancelled.set).pack(anchor='e')
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
