/**
 * The DAO (Data Access Object) for the Stock table.
 *
 * @sammatime22
 */
package com.stockrate.rest.stockrate.dao;

import com.stockrate.rest.stockrate.model.StockModel;

import java.util.List;

import org.springframework.data.repository.CrudRepository;
import org.springframework.data.jpa.repository.Query;

public interface StockDAO extends CrudRepository<StockModel, Long> {

    @Query(value = "SELECT stock FROM Stock stock")
    public List<StockModel> findAllStocks();

}
