/**
 * The Stock Model, representing the STOCK table within the DB.
 *
 * @sammatime22, 2022
 */
package com.stockrate.rest.stockrate.model;

import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.Id;
import javax.persistence.Table;

@Entity
@Table(name = "STOCK")
public class StockModel {

    @Id
    @Column(name = "stock_id")
    private short stockId;

    @Column(name = "stock_name")
    private String stockName;

    @Column(name = "acronym")
    private String acronym;

    @Column(name = "price")
    private float price;

    @Column(name = "rate_of_change")
    private float rateOfChange;

    public StockModel() {

    }

    public StockModel(short stockId, String stockName, String acronym, float price, float rateOfChange) {
        this.stockId = stockId;
        this.stockName = stockName;
        this.acronym = acronym;
        this.price = price;
        this.rateOfChange = rateOfChange;
    }

    public short getStockId() {
        return stockId;
    }

    public String getStockName() {
        return stockName;
    }

    public String getAcronym() {
        return acronym;
    }

    public float getPrice() {
        return price;
    }

    public float getRateOfChange() {
        return rateOfChange;
    }

    /**
     * Returns a string of all of the information within the StockModel object.
     *
     * @return a string of all of the information within the StockModel object
     */
    public String toString() {
        return
            "{stockId: " + stockId +
            ", stockName: " + stockName +
            ", acronym: " + acronym +
            ", price: " + price +
            ", rateOfChange: " + rateOfChange + "}";
    }
}
