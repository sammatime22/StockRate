/**
 * Controller/Rest Interface for StockRate.
 *
 * @sammatime22, 2022
 */
package com.stockrate.rest.stockrate.controller;

import com.stockrate.rest.stockrate.model.StockModel;
import com.stockrate.rest.stockrate.service.StockRateService;

import java.util.List;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class StockRateController {

    private final StockRateService stockRateService;

    /**
     * Constructor for the StockRateController.
     *
     * @param stockRateService The stock rate service used by the controller.
     */
    public StockRateController(StockRateService stockRateService) {
        this.stockRateService = stockRateService;
    }

    /**
     * Returns all stocks within the database.
     *
     * @return all of the stocks within the database
     */
    @GetMapping(value="/all")
    List<StockModel> findAllStocks() {
        return stockRateService.findAllStocks();
    }

}