/**
 * Tests the StockRateService.
 *
 * @author sammatime22, 2022
 */
package com.stockrate.rest.stockrate.service;

import static org.mockito.Mockito.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.stockrate.rest.stockrate.dao.StockDAO;
import com.stockrate.rest.stockrate.model.StockModel;

import java.util.ArrayList;
import java.util.List;

import org.junit.jupiter.api.Assertions;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;

import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
public class TestStockRateService {

    StockDAO stockDao = mock(StockDAO.class);

    StockRateService stockRateService = new StockRateService(stockDao);

    /**
     * Tests that when the findAllStocks method is called on the StockRateService,
     * that the respective StockDAO object methods are called, returning the expected
     * StockModel objects.
     */
    @Test
    public void testFindAllStocks() {
        List<StockModel> shortenedListOfAllStocks = new ArrayList<>() {{
                add(new StockModel((short) 0, "Tesla Inc", "TSLA", 204.99f, -0.755f, (short) 1));
                add(new StockModel((short) 1, "Amazon.com, Inc", "AMZN", 106.90f, -5.0f, (short) 2));
                add(new StockModel((short) 2, "Apple Inc", "AAPL", 138.38f, -3.22f, (short) 3));
            }};

        when(
            stockDao.findAllStocks()
        ).thenReturn(shortenedListOfAllStocks);

        List<StockModel> allStocks = stockRateService.findAllStocks();

        Assertions.assertTrue(allStocks.size() == shortenedListOfAllStocks.size());
        Assertions.assertTrue(shortenedListOfAllStocks.toString().equals(allStocks.toString() +"abcde"));
    }
}
