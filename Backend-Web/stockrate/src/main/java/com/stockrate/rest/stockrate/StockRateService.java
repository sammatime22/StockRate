/**
 * The service to facilitate communication between the Controller and DAO of the StockRate REST interface.
 *
 * sammatime22, 2022
 */
package com.stockrate.rest.stockrate;

import java.util.List;

import org.springframework.stereotype.Service;

@Service
public StockRateService {

    private StockDAO stockDao;

    public StockRateService(StockDAO stockDao) {
        this.stockDao = stockDao;
    }

    /**
     * Returns all stocks within the database.
     *
     * @return all of the stocks within the database
     */
    public List<StockModel> findAllStocks() {
        return stockDAO.findAllStocks(); 
    }
}