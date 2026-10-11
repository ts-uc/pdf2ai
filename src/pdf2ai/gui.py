"""Small Tk desktop interface; conversion runs off the UI thread."""
import queue
import threading
from pathlib import Path
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError as exc:
    raise SystemExit("GUIにはTkinterが必要です。READMEのインストール手順を確認してください。CLI版はTkinterなしで使用できます。") from exc
from .vector import ConversionError
from .gui_jobs import run_jobs, plan_jobs
import pikepdf


def main():
    root = tk.Tk()
    root.title("PDF → Illustrator 2020")
    root.geometry("760x680")
    root.minsize(700,640)
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
    running = False
    status = tk.StringVar(value='PDFと出力先を選択してください。')
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
    ttk.Entry(row,textvariable=page,width=16).pack(side="left",padx=8)
    ttk.Checkbutton(frame,text="Ghostscriptで前処理する（補助的な文字アウトライン化）",variable=outline).pack(anchor="w",pady=4)
    ttk.Checkbutton(frame,text="未対応機能を画像化せずエラーにする",variable=strict).pack(anchor="w",pady=4)
    ttk.Checkbutton(frame,text='選択ページを1つのAIにまとめる',variable=combine).pack(anchor='w')
    ttk.Checkbutton(frame,text='JSONレポートを保存する',variable=report_selected).pack(anchor='w')
    row = ttk.Frame(frame);row.pack(fill='x')
    ttk.Label(row,text='画像化解像度（72〜1200dpi）').pack(side='left')
    ttk.Entry(row,textvariable=dpi,width=8).pack(side='left')
    ttk.Label(frame,textvariable=status,wraplength=700).pack(anchor='w',pady=6)
    progress = ttk.Progressbar(frame,mode='determinate')
    progress.pack(fill='x')
    log = tk.Text(frame,height=8,state="disabled")

    def write(text):
        log.configure(state="normal");log.insert("end",text+"\n");log.see("end");log.configure(state="disabled")

    def run():
        nonlocal running
        if not files or not Path(folder.get()).is_dir():
            messagebox.showerror("入力の確認","PDFと出力先ディレクトリを選択してください。");return
        try:
            try:
                resolution = float(dpi.get())
                if not 72 <= resolution <= 1200: raise ValueError()
            except ValueError:
                raise ConversionError('画像化解像度は72〜1200の数値で指定してください。')
            expression = page.get().strip()
            combined = combine.get()
            if combined and outline.get():
                messagebox.showerror('入力の確認','結合とGhostscript前処理は現在併用できません。');return
            selected = list(files);directory = Path(folder.get())
            plans = plan_jobs(selected,directory,expression,combined)
            outputs = [out.resolve() for _,out,_ in plans]
        except (ValueError, OSError, pikepdf.PdfError) as error:
            messagebox.showerror('入力の確認',str(error));return
        outline_selected = outline.get()
        strict_selected = strict.get()
        write_report = report_selected.get()
        report_path = directory/'pdf2ai.report.json'
        if write_report and report_path.is_dir():
            messagebox.showerror('入力の確認','レポートと同名のフォルダーがあります。保存先を変更してください。');return
        if write_report and report_path.resolve() in {p.resolve() for p in selected} | set(outputs):
            messagebox.showerror('入力の確認','レポートの保存先が入力または出力と衝突しています。');return
        existing = [out for _,out,_ in plans if out.exists()]
        if write_report and report_path.exists(): existing.append(report_path)
        overwrite = bool(existing)
        if existing and not messagebox.askyesno('上書き確認',f'{len(existing)}件の既存ファイルを上書きしますか？'):return
        cancelled.clear()
        running = True
        for control in controls: control.configure(state='disabled')
        cancel.configure(state='normal')
        total = sum(len(s) if combined else 1 for _,_,s in plans)
        progress.configure(value=0,maximum=total)
        status.set('変換を開始します。')
        try:
            threading.Thread(target=run_jobs,kwargs=dict(plans=plans,combined=combined,overwrite=overwrite,
                strict=strict_selected,outline=outline_selected,resolution=resolution,
                cancelled=cancelled.is_set,emit=messages.put,report_path=report_path if write_report else None),daemon=True).start()
        except (RuntimeError,OSError) as error:
            messages.put(('log',f'変換処理を開始できませんでした: {error}'))
            messages.put(('done',{'total':total,'saved':0,'failed':0,'cancelled':False,
                                 'unprocessed':total,'report_error':None,'worker_error':str(error),
                                 'elapsed_seconds':0}))

    start = ttk.Button(frame,text="変換",command=run);start.pack(anchor="e",pady=8)
    def request_cancel():
        cancelled.set()
        cancel.configure(state='disabled')
        status.set('キャンセル待ち：現在の処理が安全な停止位置に達すると停止します。')
    cancel = ttk.Button(frame,text='キャンセル（処理境界で停止）',command=request_cancel,state='disabled')
    cancel.pack(anchor='e')
    log.pack(fill="both",expand=True,pady=8)
    def editable_controls(widget):
        result = []
        for child in widget.winfo_children():
            if isinstance(child,(ttk.Button,ttk.Entry,ttk.Checkbutton)) and child is not cancel:
                result.append(child)
            result.extend(editable_controls(child))
        return result
    controls = editable_controls(frame)
    def poll():
        nonlocal running
        try:
            while True:
                message = messages.get_nowait()
                if message[0]=='done':
                    running = False
                    for control in controls: control.configure(state='normal')
                    cancel.configure(state='disabled')
                    result = message[1]
                    label = 'キャンセル' if result['cancelled'] else '完了（エラーあり）' if result['failed'] or result['report_error'] or result['worker_error'] or result['unprocessed'] else '完了'
                    summary = f"{label}：保存 {result['saved']}/{result['total']}ページ、失敗 {result['failed']}、未処理 {result['unprocessed']}（{result['elapsed_seconds']:.1f}秒）"
                    status.set(summary);write(summary)
                    progress.configure(value=result['saved']+result['failed'])
                elif message[0]=='progress':
                    progress.configure(value=message[1],maximum=message[2])
                    if not cancelled.is_set():status.set(message[3])
                else:write(message[1])
        except queue.Empty:pass
        root.after(100,poll)
    def close():
        if running:
            request_cancel()
            write('停止を待っています。処理終了後にウィンドウを閉じてください。')
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    poll();root.mainloop()


if __name__ == "__main__":main()
