/**
 * DB migrations for the mvc mvp.
 * sammatime22, 2022
 */

/**
 * Creates the database for stockrate.
 */
CREATE DATABASE stockrate;

use stockrate;

/**
 * The Stock table definition.
 */
CREATE TABLE STOCK (
    stock_id        SMALLINT(5)    NOT NULL,
    stock_name      VARCHAR(150)   NOT NULL,
    acronym         VARCHAR(6)     NOT NULL,
    price           FLOAT(10)      NOT NULL,
    rate_of_change  FLOAT(10)      NOT NULL,
    stock_ranking   SMALLINT(5)    NOT NULL,
    PRIMARY KEY (stock_id)
);
