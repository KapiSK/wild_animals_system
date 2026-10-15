実カメラの JPEG を `day.jpg`、`night.jpg`、`vegetation.jpg` 等のASCII名で配置し、
`python prepare_corpus.py corpus` を実行してください。画像は同梱していません。
画像名を変更する場合は config.yaml の image_ids も変更します。
manifest.csv は画像ID、相対パス、幅、高さ、実バイト数、SHA-256を記録します。
生成し直す前の manifest は各 run に保存されます。実験中は画像を変更しないでください。
