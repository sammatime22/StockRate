/**
 * Updates tied to simultaneous stock pulls.
 */

/* We will no longer use the search terms as a means to grab the acronyms to pull. */
ALTER TABLE DATA_SOURCES DROP COLUMN search_terms;

ALTER TABLE STOCK ADD COLUMN market VARCHAR(30) NOT NULL;