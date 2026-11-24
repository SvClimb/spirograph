# Спинограф по произвольной форме

Веб-версия: https://svclimb.github.io/spirograph/ (рисует узор в браузере и сохраняет MP4/PNG, лучше в Chrome).

Веб-приложение лежит в `spirograph-app.html`. После правок можно проверить сборку командой `python3 build.py`: она собирает `deploy/index.html` и `share/spirograph.html` (один файл со встроенной библиотекой записи видео). Каждый push в `main` сам публикует `share/spirograph.html` на GitHub Pages (`.github/workflows/pages.yml`). Скрипт `deploy/deploy.sh` остался для выкладки на свой сервер с nginx.

## Python-скрипт

`spirograph.py` катит колесо без проскальзывания вдоль формы и рендерит MP4, где перо постепенно рисует узор. Нужны Python 3, numpy, Pillow и ffmpeg.

```
python3 spirograph.py --shape line --ring-teeth 150 --wheel-teeth 52 --out line.mp4
python3 spirograph.py --shape square --side outside --ring-teeth 144 --wheel-teeth 56 --out square.mp4
python3 spirograph.py --points my_shape.csv --closed --side inside --out custom.mp4
```

Основные параметры:
- `--shape` line, wave, circle, ellipse, square, triangle, blob, или `--points файл` (CSV `x,y` по строкам либо JSON `[[x,y],...]`, с `--closed` для замкнутого контура).
- `--side inside|outside` с какой стороны замкнутой формы катится колесо. Открытая линия обходится с обеих сторон, колесо огибает концы.
- `--ring-teeth`, `--wheel-teeth` размер колеса как в настоящем спирографе: на всю форму приходится R зубцов, на колесо w. Узор замыкается через w/НОД(R,w) кругов. Можно задать `--wheel-radius` напрямую.
- `--pen` расстояние пера от центра в долях радиуса (0.85 по умолчанию), `--phase` начальный угол.
- `--duration`, `--hold`, `--fps`, `--size`, `--palette rainbow|#rrggbb`, `--hue0`, `--bg`, `--line-width`.

Рядом с видео сохраняется PNG готового узора. Если форма где-то изогнута круче радиуса колеса, скрипт предупреждает: колесо там «проваливается», лучше взять колесо поменьше.
