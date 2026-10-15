# Архитектура ORBITclip

Desktop: PySide6, clipboard history and switcher, client-side encryption,
direct and relay transports, spaces and clipboard smart actions.

Backend (separate repository): `Wolchau/kinetic-relay` on Render. `/v1` messaging,
`/v2` pairing, `/v3` presence and invitation requests. The current relay holds
packets only in memory; there is no guaranteed offline delivery or server-side archive.

Data boundary: copied content is local by default. Sending and publishing are
explicit user actions. Context collections are private. Shared relay token is temporarily included in test-only private repo at owner request; never ship publicly.

Known limitations: OS-wide shortcuts and wheel hooks need physical Windows/macOS
validation. Native screen capture and OCR need platform permissions and Tesseract.
