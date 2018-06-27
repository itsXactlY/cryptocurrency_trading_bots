# -*- coding: utf-8 -*-

import pandas as pd
import numpy as np
import datetime
import time
import logging
import ccxt
import sys
# if the below imported functions (line 13) are not in the same working directory as this file
# you need to specify the path to the functions in the line below (line 12)
#sys.path.insert(0, '/PATH/TO/FOLDER/CONTAINING/FUNCTION/IMPORTED/BELOW')
from bitfinex_data_loader import get_bitfinex_data

# ENTER BITFINEX API KEY AND SECRET HERE
bitfinex = ccxt.bitfinex({
    'apiKey': 'API_KEY_GOES_HERE',
    'secret': 'API_SECRET_GOES_HERE',
})

#========================================================================================
#===== BOT PARAMETERS ===================================================================
#========================================================================================
disable_trading = True # if set to True trading is disabled (e.g. for testing)
symbol = 'LTC/USD'
timeframe = '5m' # see lines 58 - 67
set_trailing_stop = True
trailing_stop_pct = 3.0 # stop distance in percent (%)
amount_usd_to_trade = 35
# ALMA parameters
period_ALMA = 20
offset_ALMA = 0.95
sigma_ALMA = 5
#========================================================================================
#========================================================================================
#========================================================================================

###   ADVANCED SETTINGS   ###############################################################
exchange = 'bitfinex' # this bot is optimized for long/short trading USD pairs using 
# a margin account on bitfinex
api_cooldown = 5 # exchange API cooldown time in seconds
length = int(np.ceil(period_ALMA * 1.1)) # length of the data to fetch from the exchange
bitfinex_taker_fee = 0.2 # bitfinex taker fee in percent, used to calculate actual entry and exit prices
amount_crypto = 0 # position size in respective cryptocurrency, calculated in line 212
loops_per_timeframe = 4 # how often to reevaluate the position within one timeframe
current_position = 0 # current position
old_position = 0 # old position
old_entry_price_adjusted = 0 # old/current entry price, used in log output, set in line 287
next_position = 0 # netx position, set in line 124 or 127
n_trades = 0 # counts how many trades have been done, used in log output
cumulated_profit = 0 # adds up the adjusted profits, used in log output
decimals = 4 # numbers behind decimal point when rounding
# bot inception time, used in log output
inception_time = str(datetime.datetime.fromtimestamp(int(time.time())).strftime('%d-%m-%Y %H:%M:%S'))
# dictionary of functions that are used conditional on the exchange
use_function = {'bitfinex': [get_bitfinex_data, bitfinex, ccxt.bitfinex({})]}
# dictionary of timeframes that can be used
timeframes = {'1m': 60*1000,
              '5m': 5*60*1000,
              '15m': 15*60*1000,
              '30m': 30*60*1000,
              '1h': 60*60*1000,
              '3h': 3*60*60*1000,
              '6h': 6*60*60*1000,
              '12h': 12*60*60*1000,
              '1d': 24*60*60*1000,
              '1w': 7*24*60*60*1000
              }
#########################################################################################

def bot():

    # globalize variables that are changed by the bot
    global amount_crypto
    global current_position
    global old_position
    global old_entry_price_adjusted
    global next_position
    global n_trades
    global cumulated_profit

    # initiate start time to track how long one full bot iteration takes
    start = time.time()
    
    # fetch the required data from the exchange to compute the indicator from
    df = use_function[exchange.lower()][0](symbol = symbol, timeframe = timeframe, length = length, include_current_candle = True, file_format = '', api_cooldown_seconds = 0)
    # prepare the data to be used for the actual indicator computation
    # (when this step is not done the ALMA function returns the ALMA value
    # from the last full candle, effectively omitting the most current value)
    alma_data = df['Close'].shift(-1)
    alma_data.iloc[-1] = 0

    ###   INDICATOR   ##########################################################################################
    def ALMA(data, period = 100, offset = 0.85, sigma = 6):
        '''
        ALMA - Arnaud Legoux Moving Average,
        http://www.financial-hacker.com/trend-delusion-or-reality/
        https://github.com/darwinsys/Trading_Strategies/blob/master/ML/Features.py
        '''
        m = np.floor(float(offset) * (period - 1))
        s = period / float(sigma)
        alma = np.zeros(data.shape)
        w_sum = np.zeros(data.shape)

        for i in range(len(data)):
            if i < period - 1:
                continue
            else:
                for j in range(period):
                    w = np.exp(-(j - m) * (j - m) / (2 * s * s))
                    alma[i] += data[i - period + j] * w
                    w_sum[i] += w
                alma[i] = alma[i] / w_sum[i]

        df_alma = pd.DataFrame(data = alma, index = df.index, columns = ['ALMA'])
        return df_alma

    # get the indicator values using the ALMA function above
    alma = ALMA(data = alma_data.as_matrix(), period = period_ALMA, offset = offset_ALMA, sigma = sigma_ALMA)

    ###   STRATEGY   ###########################################################################################
    # if current (t) ALMA is HIGHER than ALMA t-1 go LONG
    if alma.iloc[-1][0] >= alma.iloc[-2][0]:
        next_position = 1 # LONG
    # if current (t) ALMA is LOWER than ALMA t-1 go SHORT
    if alma.iloc[-1][0] < alma.iloc[-2][0]:
        next_position = -1 # SHORT
        
    ###   TRADING ENGINE   #####################################################################################
    # print this message when trading is disabled
    if disable_trading == True:
        print('>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<')
        print('>>>        !  CAUTION  !         <<<')
        print('>>>       TRADING DISABLED       <<<')
        print('>>>     TRADES ARE SIMULATED     <<<')
        print('>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<')

    # create a list of open orders of the respective symbol
    # used to check if trailing-stop has been hitted, cancelling old trailing-stop
    if disable_trading == False:
        symbol_orders = [order for order in use_function[exchange.lower()][1].fetch_open_orders(symbol = symbol)]
        # check if there is an open position already (maybe the trailing stop has been hitted so there is no open position anymore)
        if len(symbol_orders) == 0:
            current_position = 0

    print('>>>  TRADE LOG  <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<')
    # if there is an open position
    if current_position != 0:
 
        if next_position == -1:
            if current_position == -1:
                print('==>  HOLD SHORT  <==')

            if current_position == 1:
                # delete old TRAILING-STOP order
                if set_trailing_stop == True:
                    if disable_trading == False:
                        use_function[exchange.lower()][1].cancel_order(id = symbol_orders[-1]['id'])
                        time.sleep(api_cooldown)
                    print('Old Trailing-Stop Cancelled')

                # if trading is disabled get the first bid price from the order book as current_entry_price
                if disable_trading == True:
                    current_entry_price = round(float(use_function[exchange.lower()][2].fetch_order_book(symbol = symbol, limit = 1)['bids'][0][0]), decimals)
                # create SELL order
                if disable_trading == False:
                    use_function[exchange.lower()][1].create_market_sell_order(symbol, amount_crypto * 2, {'type': 'market'})
                    time.sleep(api_cooldown)
                current_position = -1
                print('==>  ENTERED SHORT  <==')

                # create TRAILING-STOP order, BUY
                if set_trailing_stop == True:
                    if disable_trading == False:
                        symbol_trades = [trade for trade in use_function[exchange.lower()][1].fetch_my_trades(symbol = symbol)]
                        use_function[exchange.lower()][1].create_order(symbol = symbol, type = 'trailing-stop', side = 'buy', amount = amount_crypto, price = round(float(symbol_trades[-1]['price']) * (trailing_stop_pct / 100), 4))
                    print('Trailing-Stop Placed (BUY)')

        if next_position == 1:
            if current_position == 1:
                print('==>  HOLD LONG  <==')

            if current_position == -1:
                # delete old TRAILING-STOP order
                if set_trailing_stop == True:
                    if disable_trading == False:
                        use_function[exchange.lower()][1].cancel_order(id = symbol_orders[-1]['id'])
                        time.sleep(api_cooldown)
                    print('Old Trailing-Stop Cancelled')

                # if trading is disabled get the first ask price from the order book as current_entry_price
                if disable_trading == True:
                    current_entry_price = round(float(use_function[exchange.lower()][2].fetch_order_book(symbol = symbol, limit = 1)['asks'][0][0]), decimals)
                # create BUY order
                if disable_trading == False:
                    use_function[exchange.lower()][1].create_market_buy_order(symbol, amount_crypto * 2, {'type': 'market'})
                    time.sleep(api_cooldown)
                current_position = 1
                print('==>  ENTERED LONG  <==')

                # create TRAILING-STOP order, SELL
                if set_trailing_stop == True:
                    if disable_trading == False:
                        symbol_trades = [trade for trade in use_function[exchange.lower()][1].fetch_my_trades(symbol = symbol)]
                        use_function[exchange.lower()][1].create_order(symbol = symbol, type = 'trailing-stop', side = 'sell', amount = amount_crypto, price = round(float(symbol_trades[-1]['price']) * (trailing_stop_pct / 100), 4))
                    print('Trailing-Stop Placed (SELL)')

    # if there is no position yet or the position was closed within the timeframe (trailing-stop hitted)
    if current_position == 0:

        # set the amount to be traded in respective cryptocurrency as (amount_usd_to_trade) / (current average price of the cryptocurrency)
        amount_crypto = round(float(amount_usd_to_trade / use_function[exchange.lower()][2].fetch_ticker(symbol = symbol)['last']), 8)
        
        if next_position == 1:
            # if trading is disabled get the first ask price from the order book as current_entry_price
            if disable_trading == True:
                current_entry_price = round(float(use_function[exchange.lower()][2].fetch_order_book(symbol = symbol, limit = 1)['asks'][0][0]), decimals)
            # create BUY order
            if disable_trading == False:
                use_function[exchange.lower()][1].create_market_buy_order(symbol, amount_crypto, {'type': 'market'})
                time.sleep(api_cooldown)
            current_position = 1
            print('Initial LONG (Market Order)')

            # create TRAILING-STOP order, SELL
            if set_trailing_stop == True:
                if disable_trading == False:
                    symbol_trades = [trade for trade in use_function[exchange.lower()][1].fetch_my_trades(symbol = symbol)]
                    use_function[exchange.lower()][1].create_order(symbol = symbol, type = 'trailing-stop', side = 'sell', amount = amount_crypto, price = round(float(symbol_trades[-1]['price']) * (trailing_stop_pct / 100), 4))
                print('Initial Trailing-Stop (SELL)')

        if next_position == -1:
            # if trading is disabled get the first bid price from the order book as current_entry_price
            if disable_trading == True:
                current_entry_price = round(float(use_function[exchange.lower()][2].fetch_order_book(symbol = symbol, limit = 1)['bids'][0][0]), decimals)
            # create SELL order
            if disable_trading == False:
                use_function[exchange.lower()][1].create_market_sell_order(symbol, amount_crypto, {'type': 'market'})
                time.sleep(api_cooldown)
            current_position = -1
            print('Initial SHORT (Market Order)')

            # create TRAILING-STOP order, BUY
            if set_trailing_stop == True:
                if disable_trading == False:
                    symbol_trades = [trade for trade in use_function[exchange.lower()][1].fetch_my_trades(symbol = symbol)]
                    use_function[exchange.lower()][1].create_order(symbol = symbol, type = 'trailing-stop', side = 'buy', amount = amount_crypto, price = round(float(symbol_trades[-1]['price']) * (trailing_stop_pct / 100), 4))
                print('Initial Trailing-Stop (BUY)')

    time.sleep(api_cooldown)
    if disable_trading == False:
        current_entry_price = float(bitfinex.fetch_my_trades(symbol = symbol, limit = 1)[0]['info']['price'])

    ###   END OF TRADER   ######################################################################################

    ###   LOG OUTPUT   #########################################################################################
    # only show output when the position changes
    if next_position != old_position:
        n_trades += 1
        print('>>>  BOT LOG  <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<')
        print('  < ' + symbol + ' | ' + timeframe + ' | ' + exchange + ' | Iterations: ' + str(loops_per_timeframe) + ' | Inception: ' + inception_time + ' >')
        print('| Strategy: \t\t\t\tMomentum ALMA')
        print('| Amount to Trade: \t\t\t' + str(amount_usd_to_trade) + ' USD')
        if disable_trading == False:
            print('| Trailing Stop: \t\t\t' + str(set_trailing_stop))
            if set_trailing_stop == True:
                print('| Trailing Stop Distance: \t\t' + str(trailing_stop_pct) + '%')
        print('| Date and Time: \t\t\t' + str(datetime.datetime.fromtimestamp(int(time.time())).strftime('%d-%m-%Y %H:%M:%S')))
        print()
        if old_position != 0:
            print(' --  Old Position: \t\t\t' + ('LONG' if int(old_position) == 1 else 'SHORT'))
        print(' --  Current Position: \t\t\t' + ('LONG' if int(current_position) == 1 else 'SHORT'))
        print(' --  Amount Crypto: \t\t\t' + str(round(amount_crypto, 5)) + '\t' + str(symbol.split('/')[0]))
        print(' --  Entry Price (Fee Adj.): \t\t' + str(round(float(current_entry_price * (1 + (bitfinex_taker_fee / 100))) if next_position == 1 else float(current_entry_price * (1 - (bitfinex_taker_fee / 100))), decimals)) + '\t' + str(symbol.split('/')[1]))
        print(' --  Entry Price: \t\t\t' + str(current_entry_price) + '\t' + str(symbol.split('/')[1]))
        print(' --  Current Price: \t\t\t' + str(df['Close'].iloc[-1]) + '\t' + str(symbol.split('/')[1]))
        print()
        # the below is printed only after the first position is exited
        if old_entry_price_adjusted != 0:
            print(' --  Old Entry Price (Fee Adj.): \t' + str(round(old_entry_price_adjusted, decimals)) + '\t' + str(symbol.split('/')[1]))
            adjusted_profit = ((((float(current_entry_price * (1 + (bitfinex_taker_fee / 100))) if next_position == 1 else float(current_entry_price * (1 - (bitfinex_taker_fee / 100)))) - old_entry_price_adjusted) / old_entry_price_adjusted) * 100 * int(old_position))
            print(' --  Approximate P/L (Fee Adj.): \t' + str(round(adjusted_profit, decimals)) + '%')
            cumulated_profit += adjusted_profit
            print(' --  Cumulated P/L (Fee Adj.): \t\t' + str(round(cumulated_profit, decimals)) + '%')
        print(' --  Trades since Inception: \t\t' + str(n_trades))
        # if the position changed update the old entry price
        old_entry_price_adjusted = float(current_entry_price * (1 + (bitfinex_taker_fee / 100))) if next_position == 1 else float(current_entry_price * (1 - (bitfinex_taker_fee / 100)))
        # calculate fee expenses per trade (to have it available)
        position_trading_fees = current_entry_price * ((bitfinex_taker_fee * amount_crypto) / 100)
        print() # leave some space for nicely formatted output
    print(' --  Old ALMA: \t\t\t\t' + str(round(alma.iloc[-2][0], decimals)) + '\t' + str(symbol.split('/')[1]))
    print(' --  Current ALMA: \t\t\t' + str(round(alma.iloc[-1][0], decimals)) + '\t' + str(symbol.split('/')[1]))

    # update value for old_position
    old_position = current_position

    # print current date and time for reference
    print('| Date and Time: \t\t\t' + str(datetime.datetime.fromtimestamp(int(time.time())).strftime('%d-%m-%Y %H:%M:%S')))
    # sleep for ((one timeframe) / (how often to reevaluate the position within the timeframe))
    # - time it took to run one full bot iteration
    time.sleep(((timeframes[timeframe] / loops_per_timeframe) / 1000) - (time.time() - start))

# try except setup to run the bot (to catch errors and avoid stopping the bot)
def run_bot():

    while True:
        try:
            bot()
            print() # leave some space for nicely formatted output
        except Exception as e:
            logging.error(' ' + str(e)) # prints error message as error message (only the message itself)
            time.sleep(60) # wait for 60 seconds and run the bot again
            pass

# function call which ultimately runs the bot
run_bot()



