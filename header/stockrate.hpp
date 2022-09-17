/**
 * The header file for the stockrate app.
 *
 * @author sammatime22, 2022
 */
class StockRate {
    public:
        /**
         * Constructor for the StockRate application.
         *
         * @param days_out The number of days out StockRate should try to
         *                  predict the value of a given stock
         */
        StockRate(int days_out);

    private:
        // The number of days out to where StockRate should predict.
        int days_out;

        /**
         * Actually conducts the rating of the stock n number of days out.
         *
         * @param value_time_tuple_list
         */
        rater(ValueTimeTuple* value_time_tuple_list);
}

/**
 * Struct to keep track of each individual Value Time Tuple object.
 * 
 * @param time The time in question
 * @param value The value of the stock at a given point in time.
 * @param value A pointer to the next ValueTimeTuple in question
 */
struct ValueTimeTuple {
    time: long;
    value: int;
    value: ValueTimeTuple*;
}
