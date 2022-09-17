/**
 * The main class to rate stocks.
 *
 * @author sammatime22, 2022
 */ 

/**
 * Imports for StockRate - will keep after removing main method
 */
#include "stockrate.hpp"

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
        rater(ValueTimeTuple* value_time_tuple_list) {
            // determine the time intervals we will try to calculate outwards for
            // go through each value pair
                // add more to our overall trajectory vector
                // try to characterize our pattern vector
            // for each remaining interval
                // apply our characterized amount to each pattern vector portion
            // return the new output pattern
        }
}


/**
 * Imports for main - will remove as application is built
 */
#include <iostream>
#include <fstream>
#include <cstdlib>
using namespace std;

#define EXPECTED_NUMBER_OF_ARGS 2
#define INPUT_FILE_POS 1

int main(int argv, char*[] argc) {
    // only temporary - will remove as stack becomes defined
    if (argv != EXPECTED_NUMBER_OF_ARGS) {
        cout << "The correct number of args expected " <<
            "(in this primitive version of the app) were not provided." << endl;
        cout << "Usage: ./stockrate <path to your file>" << end;
        exit(1);
    }

    // read in user input 
    ifstream input_file;

    input_file.open(argc[INPUT_FILE_POS]);

    if (input_file.fail()) {
        cout << "Could not read in " << argc[INPUT_FILE_POS] << endl;
    }

    // if user provided bad input
        // tell them at the console
    // else
        // print out return values
}
