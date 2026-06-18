# Research Sources

Product data starts with Open Beauty Facts bulk exports and the Open Food Facts API documentation. Ingredient and risk enrichment use public, source-backed references:

- Open Beauty Facts/Open Food Facts product database and API docs.
- EWG Skin Deep product and ingredient data through archive.org Wayback captures. The app stores raw EWG source payloads, keeps unmodeled parsed facts in `source_record_facts`, normalizes product attributes and concern buckets into canonical terms, and keeps EWG provenance separate from Open Beauty Facts provenance.
- EU CosIng and SCCS references.
- Cosmetic Ingredient Review reports.
- FDA cosmetic allergen guidance.
- FDA alpha hydroxy acid and beta hydroxy acid cosmetic guidance.
- FDA hair dye, formaldehyde hair smoothing, and skin-lightening product safety guidance.
- SCCS scientific opinions for methylisothiazolinone, salicylic acid children's exposure, vitamin A/retinoids, resorcinol, and alpha/beta-arbutin.
- American Academy of Dermatology pregnancy skin-care and retinoid guidance.
- European Medicines Agency retinoid pregnancy-prevention guidance.
- openFDA cosmetic adverse-event endpoint.
- PubChem PUG-REST and PUG-View.
- IFRA Standards Library.
- ZXing-C++ Python bindings for barcode reading.
- PaddleOCR/PaddleX local OCR pipeline documentation.
- Sentence Transformers image search docs for CLIP image embeddings.
- sqlite-vec Python and `vec0` docs for local SQLite vector search.

The app treats source data as evidence with confidence, not as medical certainty.
