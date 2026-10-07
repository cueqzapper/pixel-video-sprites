# pixel-video-sprites

**Pixelgenaue Sprite-Animationen aus einem Video-Modell.** Ein natives Sprite und ein Satz Text rein, eine fertige
Pixel-Animation raus – gehen, verwandeln, angreifen, schwanken –, gerechnet auf deinem eigenen ComfyUI.

Beispiele aus unserem Jump’n’Run **KNUDDEL-ALARM**, erzeugt aus den vorhandenen Spiel-Sprites und als Spiel-Assets abgelegt:

| Wackelpudding wird geheilt | Gewitterwolke wird geheilt | Grummelbär stapft | Gewitterwolke blitzt | Boss schwankt (64×80) |
|---|---|---|---|---|
| ![](examples/knuddel-jelly-cure/preview.gif) | ![](examples/knuddel-cloud-cure/preview.gif) | ![](examples/knuddel-bear-walk/preview.gif) | ![](examples/knuddel-cloud-attack/preview.gif) | ![](examples/knuddel-baron-dizzy/preview.gif) |
| einmalig, 8 Frames | einmalig, 6 Frames | Schleife, 6 Frames | einmalig, 8 Frames | Schleife, 6 Frames |

Jeder Beispiel-Ordner enthält das Eingabe-Sprite (`input.png`), die Frames so, wie sie im Spiel liegen (`frames/`, auf einen
Fusspunkt ausgerichtet), ein `spritesheet.png`, das `preview.gif` und die genauen Einstellungen (`recipe.json`). Nichts davon
ist von Hand nachgebessert.

Frühe Prüf-Animationen (die ersten Tests der Kette):

| Betrunkener trinkt | Geier fliegt | Käfer explodiert | Hase rennt (schwach) |
|---|---|---|---|
| ![](examples/drunk-drinks/preview.gif) | ![](examples/vulture-flies/preview.gif) | ![](examples/beetle-explodes/preview.gif) | ![](examples/bunny-run/preview.gif) |

Der Hase bleibt nur als frühes Experiment drin: Schon sein Startbild war schwach (Ohren und Schal kaum lesbar).

[English: README.md](README.md)

## Warum ein Video-Modell

Wir haben zuerst 42 Ansätze mit Bild-Modellen getestet: Edits Frame für Frame, Skelette, Silhouetten,
Laufzyklus-Vorlagen, ganze Spritesheets in einem Bild, SD 1.5/SDXL mit ControlNet, FLUX.2 Klein mit Lauf-LoRA. Die
Einzelbilder sahen gut aus, der Ablauf nie. **Bild-Modelle haben kein Gedächtnis über Frames.** Jeder Frame wird neu
erfunden, die Animation flackert. Vorlagen machen die Bewegung korrekt, aber nie allgemein: Für „Käfer explodiert“ gibt
es keine Vorlage.

Ein Video-Modell versteht beliebige Bewegung und hält die Figur über alle Frames. Es kann nur keine Pixel. Deshalb
teilen wir die Arbeit:

```
dein Sprite (≤ 64 px)
  └─ unten mittig auf flacher Key-Farbe (Grün / Magenta / Blau, automatisch), nearest auf 384²
      └─ Wan 2.2 I2V A14B: 33 Frames, Bewegung aus dem Text
         High-Noise-Stufe OHNE lightx2v-Beschleuniger (echte CFG 3,5), Low-Noise-Stufe mit
          └─ Frames wählen: loop = genau eine Bewegungsperiode, once = verteilt bis zum letzten sichtbaren Frame
              └─ Krea 2 Turbo + k2-pixel32 img2img (denoise 0,4), 6 Frames pro ComfyUI-Auftrag
                  └─ MiniMax H3 Pixel Art Refiner: exaktes Raster, EINE gemeinsame Palette für alle Frames
                      └─ Key-Farbe weg → frames/, spritesheet.png, preview.gif, meta.json
```

Was es zum Laufen gebracht hat (jeder Punkt hat uns Tage gekostet):

1. **Kein Beschleuniger auf der High-Noise-Stufe.** lightx2v (4 Schritte) dämpft die Bewegung, die Beine trippeln nur.
2. **Green Screen statt Weiss.** Weisse Figuren auf Weiss verlieren ihre Beine. Die Key-Farbe wird automatisch gewählt.
3. **Frames nach Zahl sortieren.** `v_0, v_1, v_10, v_11, … v_2` verwürfelt jedes Video, ohne dass man es merkt.
4. **Krea nachzeichnen lassen, nicht selbst rastern.** Verkleinern ergibt Matsch. Krea + k2-pixel mit niedrigem
   denoise übernimmt die Pose aus dem Video und liefert einen sauberen Pixelstrich. Eine Kunstzelle = 32 Bildpixel
   (2 × 2 Krea-Tokens).
5. **Palette sperren.** Eine Palette für alle Frames (Figurfarben + Key-Farbe). Für Effekte (`--no-hold`) kommt die
   Palette aus dem Video.
6. **„Bleib, wie du bist“ bremst grosse Aktionen.** Für Abheben und Explosionen `--no-hold`, Rand und schwächeres
   Nachzeichnen.

## Installation

1. Ein laufendes **ComfyUI** (getestet: 0.37) mit 24-GB-Grafikkarte und viel Arbeitsspeicher (wir nutzen eine RTX 4090
   und 44 GB RAM; Wan 14B lädt nacheinander zwei Modelle à ~9,7 GB).
2. Die Custom Nodes **ComfyUI-GGUF** und **ComfyUI-Krea2-Pixel-Art-Refiner** und die Modelldateien – alle mit Link,
   Zielordner und Lizenz in **[MODELS.md](MODELS.md)**. Modell-Gewichte liegen hier nicht bei.
3. Dieses Werkzeug (Python ≥ 3.10, braucht nur numpy und Pillow):

   ```bash
   pip install .            # installiert den Befehl `pvs`
   # oder ohne Installation: python -m pixel_video_sprites …
   ```

4. Alles prüfen:

   ```bash
   pvs --url http://127.0.0.1:8188 check
   ```

   Der Befehl listet fehlende Nodes und Modelldateien. Liegt eine Datei in einem Unterordner (z. B.
   `loras/krea2/k2-pixel32.safetensors`), nennt er die passende Option, z. B. `--krea lora_dir=krea2/`.

Die ComfyUI-Adresse kommt aus `--url`, sonst aus der Umgebungsvariable `COMFY_URL`, sonst `http://127.0.0.1:8188`.
Steht dein ComfyUI hinter einem Proxy mit Anmeldung, setz `COMFY_AUTH` auf `Bearer <token>`, `Basic <base64>` oder
`benutzer:passwort`. Gespeichert wird nichts.

## Benutzung

```bash
pvs animate examples/knuddel-bear-walk/input.png --view "side view facing left" \
  --action "stomps forward grumpily, swinging his short arms, the body bobbing heavily with each step, walking on the spot like on a treadmill" \
  --description "a small grumpy pink gummy bear with a dark plum outline and an angry frown" \
  --mode loop --frames 6 --stabilize scale --out out/bear-walk
```

Ergebnis in `out/bear-walk/`: `frames/frame_XX.png` (native Grösse, transparent), `spritesheet.png`, `preview.gif`,
`meta.json` (gewählte Video-Frames, Zyklus, Einstellungen, Zeiten) sowie die Zwischenstände `start.png`, `video/`,
`canvas/`, `krea/`. Aktion und Beschreibung am besten auf Englisch schreiben.

Die Befehle für die anderen Beispiele stehen in der [englischen README](README.md#usage); die genauen Einstellungen
jedes gezeigten Ergebnisses in `examples/*/recipe.json`. Ergebnisse hängen vom Seed ab (`--seed`): ein paar Varianten
machen und eine auswählen.

### Optionen

| Option | Standard | Bedeutung |
|---|---|---|
| `--mode loop\|once` | `loop` | `loop` = eine Bewegungsperiode (rennen, fliegen, Idle); `once` = einmalige Aktion (Explosion, Trinken) |
| `--frames` | 12 | Anzahl Frames (eine kürzere Periode wird ganz genommen) |
| `--margin` | 0 | zusätzliche Rasterzellen Luft: 2 Trinken, 6 Flügel, 8 Explosion |
| `--no-hold` | aus | ohne „behält Grösse und Proportionen“, Kamera folgt, Palette aus dem Video – für grosse Aktionen und Effekte |
| `--denoise` | 0,4 | Stärke des Krea-Nachzeichnens (0,3 für Effekte) |
| `--length` | 33 | Video-Frames (4n+1, z. B. 33 oder 49) |
| `--side` / `--steps` | 384 / 8 | Video-Auflösung und Wan-Schritte (die Hälfte auf der High-Noise-Stufe mit CFG 3,5) |
| `--cell 32\|16` | 32 | Krea-Zellgrösse: 32 = bester Look; 16 = k2-pixel64 auf einem Viertel der Pixel, schneller, aber Krümel bei Effekten |
| `--view` | `side view facing right` | muss zum Sprite passen (`side view facing left`, `front view`, …) |
| `--canvas` | 32 / 64 | Leinwand in Sprite-Pixeln (32 bis 30 px, sonst 64); `80` mit `--cell 16` für einen 64×80-Boss |
| `--stabilize pos\|scale` | aus | gewählte Video-Frames vor dem Nachzeichnen ruhigstellen: Fusslinie und Körpermitte (`pos`), dazu Höhe zurück auf die Sprite-Höhe (`scale`, gegen Wan-Zoom beim Hüpfen) |
| `--pick 1,2,5,…` | automatisch | eigene Auswahl der Video-Frames, z. B. nur der Teil eines einmaligen Clips, in dem die Aktion passiert |
| `--palette base\|video`, `--extra-colors "r,g,b;…"` | base (video bei `--no-hold`) | Herkunft der Palette; Zusatzfarben für `base`, z. B. dunklere Grautöne für eine Wolke, die sich verdunkelt |
| `--wan KEY=WERT`, `--krea KEY=WERT` | | beliebigen Vorlagen-Parameter überschreiben (Modell-Dateinamen, `shift`, `hi_cfg`, `lora_dir`, …) |

## Workflows

Die zwei ComfyUI-Workflows liegen in [`pixel_video_sprites/workflows/`](pixel_video_sprites/workflows/). Es sind
Workflows im ComfyUI-**API-Format** mit `{{Platzhaltern}}` und einem `_template`-Block, der jeden Parameter mit
Standardwert auflistet. Das Werkzeug füllt sie aus. Um einen im ComfyUI-Editor zu laden, zuerst die Platzhalter durch
Werte ersetzen.

## Zeiten (RTX 4090, geteilter Server)

| Einstellung | Frames | Video (Wan) | Pixel (Krea) | Gesamt |
|---|---|---|---|---|
| erste Fassung: 512², 10 Schritte, Krea je Frame einzeln | 12 | – | – | ≈ 4,5 min |
| 512², 10 Schritte, Krea 6 pro Auftrag | 12 | 63 s | 101 s | 2,7 min |
| **384², 8 Schritte, Krea 6 pro Auftrag (Standard)** | 6 | 45 s | 68 s | 2,1 min |
| **384², 8 Schritte, Krea 6 pro Auftrag (Standard)** | 12 | 46 s | 138 s | 3,1 min |
| 384², 8 Schritte, `--cell 16` | 6 | 45 s | 29 s | 1,2 min |

## Grenzen

* Abgestimmt auf native Sprites bis 64 px; grössere (ein 64×80-Boss) gehen mit `--canvas 80 --cell 16`. Die Ansicht (z. B. Seitenansicht) muss im Eingabebild schon stimmen.
* Die Figur genau beschreiben (Farben, Kleidung), sonst „korrigiert“ Krea sie.
* Nicht jeder Seed passt – ein paar Varianten machen und eine auswählen.
* Kleine Schwankungen bleiben (Ohrform, dunkle Klumpen bei schnellem Flügelschlag).
* Video-Modelle zerstören Figuren ungern; Explosionen brauchen eine klare Aktion und `--no-hold`.
* Das kleine Wan 2.2 5B (Turbo) ist schneller, hat in unseren Tests die Figur aber vergrössert, umgestaltet und die
  Pose eingefroren.

## Lizenz

MIT für alles in diesem Repository – siehe [LICENSE](LICENSE). Die Modelle gehören nicht dazu und behalten ihre eigenen
Lizenzen (siehe [MODELS.md](MODELS.md); vor kommerzieller Nutzung die **Krea 2 Community License** lesen).

Vom Team von [Daybun](https://daybun.com). Danke an die Autorinnen und Autoren von Wan 2.2, Krea 2, der
k2-pixel-LoRAs (e-n-v-y), des Krea-2-Pixel-Art-Refiners (envy-ai), von ComfyUI-GGUF (city96), der GGUF-Fassungen
(QuantStack) und an das Comfy-Team.
