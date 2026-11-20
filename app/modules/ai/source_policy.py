"""Hard-coded default-deny policy gates for user-facing knowledge sources."""

# PubMed abstracts have record-specific rights and NCBI requires its disclaimer
# to be evident to end users. Keep acquisition and retrieval closed until both
# policy reviews are complete. No runtime setting may override these gates.
PUBMED_SOURCE_NAME = "PubMed via NCBI E-utilities"
PUBMED_SOURCE_URL = "https://pubmed.ncbi.nlm.nih.gov/"
PUBMED_ACQUISITION_ENABLED = False
PUBMED_USER_FACING_ENABLED = False
