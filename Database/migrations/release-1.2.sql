/**
 * Updates tied to simultaneous stock pulls.
 * sammatime22, 2026
 */

/* We will no longer use the search terms as a means to grab the acronyms to pull. */
ALTER TABLE DATA_SOURCES DROP COLUMN search_terms;

ALTER TABLE STOCK DROP COLUMN price;
ALTER TABLE STOCK DROP COLUMN rate_of_change;
ALTER TABLE STOCK ADD COLUMN market VARCHAR(30) NOT NULL;
UPDATE STOCK SET market = SUBSTRING_INDEX(acronym, ':', -1), acronym = SUBSTRING_INDEX(acronym, ':', 1);