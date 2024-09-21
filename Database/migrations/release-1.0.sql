/**
 * DB migrations for the release-1.0.
 * sammatime22, 2024
 */

/** Stockrate #10 - Basic Stock Parser */
use stockrate;

ALTER TABLE STOCK MODIFY COLUMN stock_id SMALLINT(5) NOT NULL AUTO_INCREMENT;
ALTER TABLE STOCK DROP COLUMN stock_ranking;
ALTER TABLE STOCK MODIFY COLUMN acronym VARCHAR(30);

CREATE TABLE DATA_SOURCES (
    source_id        SMALLINT(5)    NOT NULL AUTO_INCREMENT,
    source_location  VARCHAR(512)   NOT NULL,
    extension        VARCHAR(128)   NULL,
    search_terms     TEXT           NULL,
    notes            VARCHAR(512)   NULL,
    PRIMARY KEY (source_id)
);

CREATE TABLE COLLECTED_DATA (
    pull_id     BIGINT(20)    NOT NULL AUTO_INCREMENT,
    pull_date   TIMESTAMP     NOT NULL DEFAULT(current_timestamp),
    source_id   SMALLINT(5)   NOT NULL,
    stock_id    SMALLINT(5)   NOT NULL,
    dirty_data  LONGTEXT      NULL,
    PRIMARY KEY(pull_id)
);

CREATE TABLE CLEANED_DATA (
    data_id         BIGINT(20)   NOT NULL AUTO_INCREMENT,
    stock_id        SMALLINT(5)  NOT NULL,
    pull_id         BIGINT(20)   NOT NULL,
    source_id       SMALLINT(5)  NOT NULL,
    price           FLOAT(10)    NOT NULL,
    rate_of_change  FLOAT(10)    NOT NULL,
    PRIMARY KEY(data_id)
);
