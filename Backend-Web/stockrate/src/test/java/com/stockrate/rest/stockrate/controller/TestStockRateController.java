/**
 * Tests the StockRateController.
 *
 * @author sammatime22, 2022
 */
package com.stockrate.rest.stockrate.controller;

// other imports
import static org.mockito.Mockito.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.stockrate.rest.stockrate.model.StockModel;
import com.stockrate.rest.stockrate.service.StockRateService;

import java.util.ArrayList;
import java.util.List;

import org.junit.jupiter.api.Assertions;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;

import org.mockito.junit.jupiter.MockitoExtension;

import org.springframework.test.web.servlet.request.MockMvcRequestBuilders;

@ExtendWith(MockitoExtension.class)
public class TestStockRateController {

    StockRateService stockRateService = mock(StockRateService.class);

    StockRateController stockRateController = new StockRateController(stockRateService);

    // Test that the controller will respond to a request for all stocks with all stock data
    // @Test
    // public void testFindAllStocks() {
    //     // set up test input (REST)/output (not that there shouldn't really be input)
    //     // run mock mvc test
        
    //     // Assertions.assertTrue(allStocks.size() == shortenedListOfAllStocks.size());
    //     // Assertions.assertTrue(shortenedListOfAllStocks.toString().equals(allStocks.toString()));
    // }
}