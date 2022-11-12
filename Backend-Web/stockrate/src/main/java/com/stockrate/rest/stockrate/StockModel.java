/**
 * The Stock Model, representing the STOCK table within the DB.
 *
 * @sammatime22, 2022
 */
package com.stockrate.rest.stockrate;

import javax.persistence.Entity;

@Entity
public class StockModel {

    private String stockName;

    private String stockAcronym;

    private float stockPrice;

    private float stockRateOfChange;

    private short stockRanking;

    public StockModel(String stockName, String stockAcronym, float stockPrice, float stockRateOfChange, short stockRanking) {
        this.stockName = stockName;
        this.stockAcronym = stockAcronym;
        this.stockPrice = stockPrice;
        this.stockRateOfChange = stockRateOfChange;
        this.stockRanking = stockRateOfChange;
    }

}
