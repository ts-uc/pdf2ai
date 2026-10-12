# 東洋インキの特色対応

後続のDICのみの変更で、DICは旧版カラーブックのCMYK代替値へ移行した。[DIC基準変更の記録](dic-cmyk-reference.md)。TOYOのファイルとLab定義は引き続き独立しており、以下の「DICを変更せず」はTOYO追加時点の記録。

2026-10-12。DICの色データ・名前照合コード・パレット・テストは変更せず、東洋インキのファイルを独立して追加した。共通のPDF変換処理から両方を参照する。

## ファイルと使い方

- `src/pdf2ai/toyo.py`：TOYO専用の色名照合。
- `src/pdf2ai/data/toyo_lab.json`：TOYO専用の2129色のLabとCMYK代替値。
- `integrations/scribus/palettes/TOYO_COLOR_FINDER_Lab.xml`：現行カラーブックの1079色（CF 10001〜11050の1050色と基本色29色）。
- `integrations/scribus/palettes/TOYO_94_Lab.xml`：旧版カラーブックの1050色（TOYO 0001〜1050）。
- `tests/test_toyo.py`：TOYO専用の回帰テスト。

Scribusの色設定で必要なTOYOパレットをインポートし、特色として使用する。変換の追加オプションは不要。CLI、Scribus連携、事前検査、複数アートボードの結合で共通の色名照合を使う。

正式名を優先し、末尾の星印を省略した名前も解決する。`CF10001`・`CF 10001`・`TOYO CF10001`・`TOYO CF 10001`・`TOYO 10001`は`CF 10001*`、`TOYO 1`は`TOYO 0001`へ照合する。番号だけの名前、任意の接尾辞、未知の番号は照合しない。新旧番号を近似色へ置き換えず、両カラーブックを独立した名前で保持する。同じ色の正式名と別名は1つのスウォッチになる。

塗りと線の濃度を保持する。PDFのDeviceCMYK Separationは登録済みLab値へそろえ、PDF表示とAI編集データで同じ定義を使う。D50のLab Separationは元PDFの実際のLab値を保持する。正式名と別名はPDF側でも同じ特色名へそろえ、分版名と編集スウォッチ名を一致させる。非線形の濃度関数や対応外の代替色空間は既存の拒否・画像化条件に従う。プロセスカラーへ変換済みの色から特色名を復元しない。

## データの出典と再生成

この環境のIllustrator 2026に同梱された`TOYO COLOR FINDER.acb`と`TOYO 94 COLOR FINDER.acb`からLab値を抽出した。前者のカラーブック記載年は2005。現行版の名称はここでは同梱カラーブック名を指し、メーカーのあらゆる最新製品やUV向け追加色への対応を意味しない。

抽出は[AdobeのACB形式仕様](https://www.adobe.com/devnet-apps/photoshop/fileformatashtml/)に基づく`tools/extract_toyo_books.py`で行う。Labの8ビットLは0〜100、a/bは符号付き値へ変換し、ページ埋め用の空エントリーは除く。色名のローカライズキーはカラーブック内の既定表記へ解決する。

CMYK代替値は`tools/illustrator_toyo_reference.jsx`からIllustrator 30.8.2の`convertSampleColor`で生成した。これは作業用カラー設定に依存する表示用の変換値で、インキ配合やメーカーのCMYK公式値ではない。Lab値は変換せずカラーブック値を保持する。生成済みデータを同梱するため通常の変換にIllustratorは不要。

再生成手順：`extract_toyo_books.py`に2つのACBと`--output output/toyo-book-input.json`を渡し、Illustratorで`illustrator_toyo_reference.jsx`を実行後、`make_toyo_palettes.py`を実行する。DICファイルには書き込まない。

## 検証

自動テストでは、全2129色の値・正式名・星印の省略、番号別名、未登録の特色の保持、Lab入力値の保持、不正な濃度関数・白色点の拒否、塗り・線の濃度、別名の重複統合、DICとの混在、事前検査・結合、パレットの独立性を確認する。

実機比較用の生成ツールは`tools/make_toyo_cases.py`。現行番号・旧版番号・基本色・別名混在の4ケースを用意し、`output/fidelity-check/after/toyo-conversion.json`へ変換記録を保存する。

初回対応時は全自動テスト339件成功（TOYO専用22件追加）。Illustrator 30.8.2で4ケースすべてをAI再保存・再オープンし、各ケースのアートボード1・パス9・画像0を保持した。再保存PDFにTOYOの特色名とLab Separationが残ることも確認した。別名混在のケースでは`CF10001`と`CF 10001*`が1つの特色になり、旧版`TOYO 0001`は別の特色として残る。

元PDFと再保存PDFの144dpi比較は4ケースとも平均画素差0、差16超の画素0%。構造確認は`output/fidelity-check/after/illustrator/results-toyo.tsv`、画素比較は`output/fidelity-check/after/toyo-visual.json`と`toyo-*-comparison.png`。有限の合成例の検証であり、全2129色の実印刷や分版、全カラー設定での完全一致を保証する結果ではない。

## DICと同じ観点での互換性再確認

2026-10-12、現在の出力コードで全2129色、現行番号・旧版番号・基本色・別名、100/50/25%の濃度、塗り・線、オーバープリント、透明を再検証した。Scribus 1.6.6でもTOYO現行版、旧版、DICとの混在の3文書を実際にPDF出力し、ツールで変換した。ユーザーのTOYO実原稿は今回のai_filesにはないため、実原稿の確認とは区別する。

追加検証で2点を修正した。

1. Lab入力では別名がPDF側に残り、CF10001とCF 10001*が別々の分版名になる一方、編集用スウォッチは1つになっていた。Lab値を保持したままPDFの特色名も正式名に統一し、両方で同じ版数・版名とした。
2. Scribusの非分離・非ノックアウトのCMYKページグループが、不透明なTOYO Lab特色ではPDF側に残っていた。不要なグループを省略し、初期描画インテントをIllustratorに合わせた。透明・通常以外の合成・分離/ノックアウト・プロファイル付き特色のグループは保持する。

Illustrator 30.8.2で11ケースすべて保存→閉じる→再度開く検証がPASS。全色の検証文書はアートボード3・パス12774・画像0を維持し、再保存PDFで全2129色がLab Separationとして残ることを確認した。全色の特色名と100%/50%の塗り、25%の線の濃度を全件照合した。Lab成分の最大差はPDFの数値丸めによる約0.000051。

MuPDFとGhostscriptの144/600dpiで、Scribusの3文書、別名、オーバープリント、代表色、DIC回帰例は再保存前後の画素差0。全色シートには最大1/255の丸め差があり、平均差の最大値は約0.000583/255。透明の検証例はGhostscriptで画素差0、MuPDFでは最大1/255の差が残った。完全な画素一致とは扱わない。

自動テスト488件成功。検証物は `output/fidelity-check/after/toyo-compatibility/` の `book-verification.json`、`all-book-visual-results.json`、`final-visual-results.json`、`illustrator/results-selected.tsv` に保存。DIC/TOYOのJSONデータと独立したパレット、ai_filesの全ファイルについて変更前後のSHA-256一致を確認した。CMYK版のパレットは追加していない。
