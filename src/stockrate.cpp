/**
 * The main class to rate stocks.
 *
 * @author sammatime22, 2022
 */ 

/**
 * Imports for StockRate - will keep after removing main method
 */
#include "stockrate.hpp"

#define NULL 0
#define SECONDS_IN_A_DAY 86400

class StockRate {
    public:
        /**
         * Constructor for the StockRate application.
         *
         * @param days_out The number of days out StockRate should try to
         *                  predict the value of a given stock
         */
        StockRate(int days_out) {
            this->days_out = days_out;
        }

        /**
         * Actually conducts the rating of the stock n number of days out.
         *
         * @param value_time_tuple_list
         */
        ValueTimeTuple* rater(ValueTimeTuple* value_time_tuple_list) {
            ValueTimeTuple* head = value_time_tuple_list;
            ValueTimeTuple* tail = value_time_tuple_list->next;
            double sum_of_velocities = 0;
            long values_calculated = 0;

            // We will need at the very least two values - otherwise we can't
            // truly generate a velocity and predict the future of the stock price.
            while (value_time_tuple_list->next != NULL) {
                sum_of_velocities += (value_time_tuple_list->next->value - value_time_tuple_list->value);
                values_calculated++;
                if (values_calculated > this->days_out) {
                    head = head->next;
                }
                tail = value_time_tuple_list->next;
            }

            double average_velocity = sum_of_velocities / values_calculated;

            // here we would calculate up to the next 7 potential values
            ValueTimeTuple* calculated_future_values;
            ValueTimeTuple* calculated_future_values_list_head;
            long last_time = tail->time;// really we should be using UNIX timestamps
            do {
                calculated_future_values = new ValueTimeTuple;
                calculated_future_values->value = head->value + average_velocity;
                calculated_future_values->time = last_time + SECONDS_IN_A_DAY;
                last_time += SECONDS_IN_A_DAY;
                if (calculated_future_values_list_head == NULL) {
                    calculated_future_values_list_head = calculated_future_values;
                }
                calculated_future_values = calculated_future_values->next;
                head = head->next;
            } while (head != NULL);

            return calculated_future_values_list_head;
        }

    private:
        // The number of days out to where StockRate should predict.
        int days_out;
};


/**
 * Imports for main - will remove as application is built
 */
#include <iostream>
#include <fstream>
#include <cstdlib>
using namespace std;

#define EXPECTED_NUMBER_OF_ARGS 2
#define INPUT_FILE_POS 1
#define DAYS_IN_A_WEEK 7

int main(int argc, char** argv) {
    // only temporary - will remove as stack becomes defined
    if (argc != EXPECTED_NUMBER_OF_ARGS) {
        cout << "The correct number of args expected " <<
            "(in this primitive version of the app) were not provided." << endl;
        cout << "Usage: ./stockrate <path to your file>" << endl;
        exit(1);
    }

    // read in user input 
    ifstream input_file;

    input_file.open(argv[INPUT_FILE_POS]);

    if (input_file.fail()) {
        cout << "Could not read in " << argv[INPUT_FILE_POS] << endl;
    }

    long time;
    double price;
    ValueTimeTuple* current_values_list;
    while (input_file.good()) {
        // whatever parsing actually needs to be done here .. do here..
        input_file >> time >> price;
        while (current_values_list->next != NULL) {
            current_values_list = current_values_list->next;
        }
        current_values_list = new ValueTimeTuple;
        current_values_list->time = time;
        current_values_list->value = price;
    }

    StockRate* sr = new StockRate(DAYS_IN_A_WEEK);

    ValueTimeTuple* potential_future_values_list = sr->rater(current_values_list);

    do {
        cout << potential_future_values_list->time << " | " << potential_future_values_list->value << endl;
        potential_future_values_list = potential_future_values_list->next;
    } while (potential_future_values_list != NULL);

    return 0;
}
