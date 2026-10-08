/**
 * A current version of the database tables.
 */

CREATE DATABASE stockrate;

use stockrate;

CREATE TABLE CLEANED_DATA (
    data_id         BIGINT(20)   NOT NULL AUTO_INCREMENT,
    stock_id        SMALLINT(5)  NOT NULL,
    pull_id         BIGINT(20)   NOT NULL,
    pull_date       TIMESTAMP     NOT NULL,
    source_id       SMALLINT(5)  NOT NULL,
    price           FLOAT(10)    NOT NULL,
    rate_of_change  FLOAT(10)    NOT NULL,
    PRIMARY KEY(data_id)
);

CREATE TABLE COLLECTED_DATA (
    pull_id     BIGINT(20)    NOT NULL AUTO_INCREMENT,
    pull_date   TIMESTAMP     NOT NULL DEFAULT(current_timestamp),
    source_id   SMALLINT(5)   NOT NULL,
    stock_id    SMALLINT(5)   NOT NULL,
    dirty_data  LONGTEXT      NULL,
    PRIMARY KEY(pull_id)
);

CREATE TABLE DATA_SOURCES (
    source_id        SMALLINT(5)    NOT NULL AUTO_INCREMENT,
    source_location  VARCHAR(512)   NOT NULL,
    extension        VARCHAR(128)   NULL,
    search_terms     TEXT           NULL,
    notes            VARCHAR(512)   NULL,
    PRIMARY KEY (source_id)
);

CREATE TABLE STOCK (
    stock_id        SMALLINT(5)     NOT NULL AUTO_INCREMENT,
    stock_name      VARCHAR(150)   NOT NULL,
    acronym         VARCHAR(30)     NOT NULL,
    market          VARCHAR(30)    NOT NULL,
    price           FLOAT(10)      NOT NULL,
    rate_of_change  FLOAT(10)      NOT NULL,
    PRIMARY KEY (stock_id)
);

CREATE TABLE USER (
    email     VARCHAR(512)   NOT NULL,
    PRIMARY KEY(email)
);

CREATE EVENT remove_collected_data ON SCHEDULE EVERY 1 DAY DO DELETE FROM COLLECTED_DATA WHERE pull_date < NOW() - INTERVAL 7 DAY;
SET GLOBAL event_scheduler = 1;
