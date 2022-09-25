# Used to make the StockRater, written in C++

stockrate: remove_stockrate
	g++ -o stockrate -I header src/stockrate.cpp

remove_stockrate:
	rm stockrate || true