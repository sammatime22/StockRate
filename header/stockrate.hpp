/**
 * The header file for the stockrate app.
 *
 * @author sammatime22, 2022
 */

/**
 * Struct to keep track of each individual Value Time Tuple object.
 * 
 * @param time The time in question
 * @param value The value of the stock at a given point in time.
 * @param value A pointer to the next ValueTimeTuple in question
 */
struct ValueTimeTuple {
    long time;
    double value;
    ValueTimeTuple* next;
};

