/**
 * The service to facilitate communication between the Controller and DAO of the StockRate REST interface.
 *
 * sammatime22, 2022
 */
package com.stockrate.rest.stockrate.service;

import com.stockrate.rest.stockrate.dao.StockDAO;
import com.stockrate.rest.stockrate.model.StockModel;

import java.util.List;

import org.springframework.stereotype.Service;

@Service
public class StockRateService {

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
        List<StockModel> stockModels = stockDao.findAllStocks(); 
        for (StockModel stockModel : stockModels) {
            System.out.println(stockModel);
        }
        return stockModels;
    }
}