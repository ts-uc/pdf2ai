# DIC特色を基準AIのCMYK定義へ変更

後続の[標準出力調整](illustrator-standard-output.md)で、単純な不透明なDIC 1の例は不要なページ透明グループを省くよう変更した。以下の再保存前の画素差の記述は、その変更前の記録。最新の例では再保存前・後の両方で参考AIとの144dpi画素差0を確認した。

2026-10-12。ユーザー指定の`dic1_fromai.ai`を基準とし、DIC特色をLabからCMYK代替値を持つ特色へ変更した。これは特色をプロセスカラーへ分解する変更ではない。TOYOのデータ・名前照合・パレットは別ファイルのままで、今回TOYOのLab定義は変更していない。

## 基準と変更

`dic1_fromai.ai`のAI編集データとPDF Separationは、特色名`DIC 1s`、濃度100%、CMYK 0/16/17/0%。この値はIllustrator 2026同梱の「以前のカラーブック/DIC カラーガイド.acbl」の`DIC 1s`と一致する。そのACBLにある全1280色のCMYK値を`src/pdf2ai/data/dic_cmyk.json`へ抽出した。Labからの近似変換ではない。再生成ツールは`tools/make_dic_cmyk.py`。

`dic.py`とPDFの共通特色処理は、登録済みDIC名をこのCMYK基準へ照合する。名称の省略、星印、塗りと線の濃度を保持する。Lab/ICC Lab入力も既存の検証を行ったうえでCMYK基準へそろえる。未登録のCMYK特色は元の値を保持する。非線形・不正な濃度関数を色番号照合で隠さない。

AIのPDF表示部分も、登録済みDICのSeparation名、DeviceCMYK代替色、線形の濃度関数をAI編集データと一致させる。Formの内部リソースにも適用する。自動画像化では更新済みPDFから描画し、表示と画像化した編集データの色を一致させる。複数ページの結合では、共有リソースの変更が完了してから各ページを処理する。入力ファイルは変更しない。

Scribus用パレットは従来の`integrations/scribus/palettes/DIC_Lab.xml`を使う。ユーザーの指定によりCMYK版パレットは削除し、再生成ツールもCMYK変換データのJSONだけを出力する。Labパレットから登録した特色もAI書き出し時にCMYK基準へそろえる。`dic_lab.json`も既存データとして残す。

## 検証

- 全自動テスト349件成功。DICの基準値、濃度、名前照合、PDF表示との一致、Lab/ICC Lab、Form内部、単ページ・結合・画像化、入力の保持、全1280色の変換データを確認。
- ユーザーの`dic1_exported.ai`から`output/fidelity-check/after/dic1-cmyk.ai`を再生成。`dic1.pdf`はすでに特色名が失われたプロセスカラーのPDFなので、今回の特色比較の入力には使わない。
- Illustrator 30.8.2で再保存・再オープンに成功し、アートボード1・パス1・画像0を保持。
- 基準`dic1_fromai.ai`のPDF表示と、修正AIをIllustratorで再保存したPDFの144dpi比較は平均画素差0、差16超の画素0%。1実例での一致であり、全カラー設定や印刷条件の保証ではない。

再保存前も特色のCMYK定義は基準と一致する。ただし元ScribusページのCMYK透明グループを保持するため、MuPDF表示では基準よりG/Bが1大きい（平均画素差0.10892）例がある。Illustrator再保存後の比較は差0。PDFページの合成構造を無条件に削除して一致させる変更は行っていない。

変換記録：`output/fidelity-check/after/dic1-cmyk-conversion.json`。比較：`dic1-cmyk-visual.json`と`dic1-cmyk-comparison.png`。旧出力と基準ファイルは変更していない。

## 深いリソース定義の再点検

使われていないForm XObjectのリソース定義が1100段あるPDFで、事前検査はベクター対応と判定するのに、DIC正規化の再帰走査が`RecursionError`になる問題を修正した。走査を明示的なスタックへ変更し、循環・共有リソースの重複検査も維持する。

実際に描画するFormの既存の入れ子上限は維持する。上限を超える描画ではstrict診断を返し、通常変換では画像化へ進める。単ページ・結合・CLI、未使用の深い定義、循環、strict時の既存AI保護・画像化の5件を追加し、全370テスト成功。参考用AIは変更していない。
