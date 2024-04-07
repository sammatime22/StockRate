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


/**
 * Boilerplate data I will use just to test the app works.
 */
INSERT INTO STOCK (stock_id, stock_name, acronym, price, rate_of_change, stock_ranking) VALUES 
    (0, "Tesla Inc", "TSLA", 204.99, -0.755, 1),
    (1, "Amazon.com, Inc", "AMZN", 106.90, -5.0, 2),
    (2, "Apple Inc", "AAPL", 138.38, -3.22, 3),
    (3, "Alibaba Group Holding Ltd", "BABA", 73.02, -2.65, 4),
    (4, "Alphabet Inc Class A", "GOOGL", 96.56, -2.52, 5),
    (5, "Microsoft Corporation", "MSFT", 228.56, -2.42, 6),
    (6, "Meta Platforms Inc", "META", 126.76, -2.71, 7),
    (7, "Carnival Corp", "CCL", 7.13, 0.42, 8),
    (8, "Nio Inc", "NIO", 11.75, -8.06, 9),
    (9, "Bank of America Corp", "BAC", 31.70, 0.0032, 10),
    (10, "Ford Motor Company", "F", 11.67, -0.85, 11),
    (11, "AT&T Inc", "T", 14.99, -0.86, 12),
    (12, "Wells Fargo & Co", "WFC", 43.17, 1.86, 13),
    (13, "Hewlett Packard Enterprise Co", "HPE", 12.59, -1.87, 14),
    (14, "Coca-Cola Co", "KO", 54.98, -1.59, 15),
    (15, "Walt Disney Co", "DIS", 94.45, -2.27, 16),
    (16, "Netflix Inc", "NFLX", 230.00, -1.08, 17),
    (17, "American Airlines Group Inc", "AAL", 13.11, 0.46, 18),
    (18, "Boeing Co", "BA", 133.15, 0.57, 19),
    (19, "Pfizer Inc.", "PFE", 42.86, -0.28, 20);
