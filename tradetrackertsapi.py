#!/usr/bin/env python

########################################################################
# Title: StreamingForumExample.py
#
# This file is designed to demonstrate placing automated trades using
# the TradeStation web API. A moving average 2 lines strategy is
# used to determine trade signals. When this file is first run, the user
# is prompted for the following: account, symbol, and quanity.
#
# The python requests module is used to issue GET and POST requests.
########################################################################

from datetime import datetime, timedelta
import json
import logging
import re
import requests
import sys
import time
import threading
import pandas as pd
import time

API_KEY = '800876E7-E895-4A20-8D13-D2F42090D696'
SECRET_KEY = '940f67d2579b331fdde56f326b389f27e42e'
REFRESH_TOKEN = 'QmhvNTRLb1FzTm1Zb3dKYnU4dVRIUXlaNTdoclNiWmZaNG5XcjdoS3A1cEo0Kzc4NjBLWUp5dUNiWW83MzFKUWJDaUZxcFhZdEZvQUdyQzZxYWgxRys2Ykp3d3FWaFFXYXU4dWZQNjByYWlIS3ErbmM1QlBOVnRPU2d2OWRXbEI2R0lrczFjR2ZoR0dkQVFuWndKSVpRZHM4ZmZaeVljdUlOQmVjYTlURmdHY3JuejN0d3JxK1IrbnJtdUZVeDU1Risrcks0VlFVSE1DVUJYaGlSQzdpZHFHc21WTThiSk9yaC9yT0E2ZnFEd1dYTDVDdHZpOGlRenJIcENRN3dkUA=='
USER_ID = 'dmktrader'
LOG_FILE = r'stream_log.txt'
# 
API_BASE_URL = 'https://sim-api.tradestation.com/v2'  # Without trailing slash # Original
#API_BASE_URL = 'https://api.tradestation.com/v2/stream/tickbars/{symbol}/{interval}/{barsBack}' #
#API_BASE_URL = 'https://api.tradestation.com/v2/stream/tickbars/{symbol}/{interval}/{barsBack}' #
#"https://api.tradestation.com/v2/stream/tickbars/AMZN/5/10?SessionTemplate=USEQPreAndPost&access_token=1JUjFiNFFGWEdDM"
#API_BASE_URL = 'https://api.tradestation.com/v2/stream/tickbars/SPY/5/10'

REDIRECT_URI = 'http://localhost:8081'

# Class defining an account using account number, alias, and key
# Alias may be an empty string if alias does not exist for the given account

class Account:

    def __init__(self, account_name, account_alias, account_key):

        self.number = account_name  # Synonymous with account number
        self.alias = account_alias
        self.key = account_key


# Class to handle indicator calculations

class Indicators:

    def __init__(self, stream):
        self.stream = stream

    # Returns the calculated moving average value
    def movAvg1Line(self, length=10):

        if len(self.stream.closing_prices) < length:
            return None

        # Handle intra-bar vs. bar close calculations differently
        if Stream.isTickClose(self.stream.bar_status):
            mov_avg = sum(self.stream.closing_prices[:length]) / length
        else:
            mov_avg = (
                sum(self.stream.closing_prices[:length-1]) + self.stream.close
            ) / length

        return mov_avg

    # Returns a dictionary containing 2 moving averages: 'fast' and 'slow'
    # Returns None if there are not enough closing prices to calculate
    def movAvg2Lines(self, fast_length=10, slow_length=20):

        if len(self.stream.closing_prices) < max([fast_length, slow_length]):
            return None

        mov_avg_values = {}

        # Handle intra-bar vs. bar close calculations differently
        if Stream.isTickClose(self.stream.bar_status):
            mov_avg_values['fast'] = sum(
                self.stream.closing_prices[:fast_length]) / fast_length
            mov_avg_values['slow'] = sum(
                self.stream.closing_prices[:slow_length]) / slow_length
        else:
            mov_avg_values['fast'] = (
                sum(self.stream.closing_prices[:fast_length-1]
                    ) + self.stream.close
            ) / fast_length
            mov_avg_values['slow'] = (
                sum(self.stream.closing_prices[:slow_length-1]
                    ) + self.stream.close
            ) / slow_length

        return mov_avg_values


# Class to handle streaming data

class Stream:

    status_bitmap = {
        0: 'NEW',
        1: 'REAL_TIME_DATA',
        2: 'HISTORICAL_DATA',
        3: 'STANDARD_CLOSE',
        4: 'END_OF_SESSION_CLOSE',
        5: 'UPDATE_CORPACTION',
        6: 'UPDATE_CORRECTION',
        7: 'ANALYSIS_BAR',
        8: 'EXTENDED_BAR',
        19: 'PREV_DAY_CORRECTION',
        23: 'AFTER_MARKET_CORRECTION',
        24: 'PHANTOM_BAR',
        25: 'EMPTY_BAR',
        26: 'BACKFILL_DATA',
        27: 'ARCHIVE_DATA',
        28: 'GHOST_BAR',
        29: 'END_OF_HISTORY_STREAM',
    }

    def __init__(self, client, symbol, bar_type, interval=5, days_back=5, session_template="Default", update_intrabar=False):
        logging.info("Initializing Stream")
        self.client = client
        self.symbol = symbol
        self.bar_type = bar_type
        self.interval = interval
        self.days_back = days_back
        self.session_template = session_template
        self.update_intrabar = update_intrabar
        self.bar_status = None
        self.close = None
        self.open = None#
        self.high = None#
        self.low = None#
        self.volume = None
        self.time = None
        self.closing_prices = []
        self.closing_times = []
        self.closing_volumes = []
        self.url = self.getStreamUrl()
        self.bar_data = pd.DataFrame()

    # Gets streaming url based on instance attributes
    def getStreamUrl(self):

        self.client.refreshAccessToken()

        if self.bar_type.lower() == 'tick':
            # 10 is the highest number of ticks back
            url = API_BASE_URL + \
                f"/stream/tickbars/{self.symbol}/{str(self.interval)}/10?access_token={self.client.access_token}&heartbeat=true"
        else:
            url = API_BASE_URL + \
                f"/stream/barchart/{self.symbol}/{str(self.interval)}/{self.bar_type.capitalize()}?SessionTemplate={self.session_template}&daysBack={str(self.days_back)}&access_token={self.client.access_token}&heartbeat=true"

        return url

    # Process stream
    def stream(self):

        self.client.refreshAccessToken()

        i = Indicators(self)
        r = requests.get(self.url, stream=True)
        strategy_position = 'Flat'

        try:
            for line in r.iter_lines():
                if line:
                    # If data is successfully stored
                    if self.storeStream(line):
                        
                        # Check if update_intrabar flag was set to false and
                        # continue onto the next stream update if tick is not a closing tick
                        if self.update_intrabar == False and not Stream.isTickClose(self.bar_status):
                            continue

                        # Indicator call
                        ma_2_lines = i.movAvg2Lines(
                            fast_length=9, slow_length=18)

                        if ma_2_lines:

                            trade = ""
                            # Only check for new trade opportunity on bar close
                            if Stream.isTickClose(self.bar_status):
                                if ma_2_lines['fast'] > ma_2_lines['slow']:
                                    if strategy_position == "Short":
                                        # Only send order if tick is real-time
                                        if Stream.isTickRealtime(self.bar_status):
                                            self.client.goLong()
                                        trade = 'Buy'
                                    strategy_position = 'Long'
                                elif ma_2_lines['fast'] < ma_2_lines['slow']:
                                    if strategy_position == "Long":
                                        # Only send order if tick is real-time
                                        if Stream.isTickRealtime(self.bar_status):
                                            self.client.goShort()
                                        trade = 'Sell Short'
                                    strategy_position = 'Short'

                            bar_info_1 = "Bar Status: {}".format(
                                Stream.getBarStatusDescription(self.bar_status)
                            )

                            bar_info_2 = "Bar Time: {}, Open: {}  High:{} Low: {} Close: {} Volume: {} Fast MA: {:0.6f} Slow MA: {:0.6f} Position: {} Trade: {}\n".format(
                                Stream.convertEpocTime(self.time),
                                self.open,#
                                self.high,#
                                self.low,#
                                self.close,
                                self.volume,
                                ma_2_lines['fast'],
                                ma_2_lines['slow'],
                                strategy_position,
                                trade
                            )
                            
                            # self.bar_data = self.bar_data.append({'Bar Time': self.time, 'close':self.close, 'Volume': self.volume})
                            with open(r"C:\Users\Charlie\Documents\CVE\Python\API\TradeTracker - Live Graph\live_close.txt", 'w') as f:
                                f.write(f'{self.close}')
                                #f.write(f'{Stream.convertEpocTime(self.time)}, {self.open}, {self.high}, {self.low}, {self.close}, {self.volume}')
                            # Write self.close to cell in google sheet
                            
                            ### Below can be copied into the console to create the 'test' file in the variable explorer
                            # with open(r'C:\Users\Charlie\Documents\CVE\Python\TS WebAPI\live_data_test.txt', 'r') as f:
                            #     test = f.read()
                                
                            # print(self.bar_data)
                            
                           #store(Stream.convertEpocTime(self.time), self.close, self.volume)

                            print(bar_info_1)
                            print(bar_info_2)

                            logging.info(bar_info_1)
                            logging.info(bar_info_2)
        
        except:

            #logging.warn('Restarting connection')#Changed 10/02/21
            logging.warning('Restarting connection')
            print('Sam is sabotaging us')
            # Re-open connection
            self.stream()

    # Stores the data from the stream in the class instance
    # Returns True only if data can be stored
    # Else returns False
    def storeStream(self, line):

        if len(line) == 0:
            return False

        try:
            decoded_line = line.decode('utf-8')
            data = json.loads(decoded_line)
        except:
            return False

        # If not hearbeat (hearbeat timestamp key has no capitalization)
        if "TimeStamp" in data:

            timestamp = data['TimeStamp']
            m = re.search(r"(\d+)", timestamp)

            if m:
                self.bar_status = data['Status']
                self.open = data['Open']#
                self.close = data['Close']
                self.high = data['High']#
                self.low = data['Low']#
                self.time = int(m.group(0))
                self.volume = data['TotalVolume']
                if Stream.isTickClose(self.bar_status):
                    self.closing_times.insert(0, self.time)
                    self.closing_prices.insert(0, self.close)
                    self.closing_volumes.insert(
                        0, data['TotalVolume'])
                return True
        return False

    # Converts an epoch number into a formatted text string
    @staticmethod
    def convertEpocTime(epoch_time):

        try:
            return time.strftime(
                "%m/%d/%Y %H:%M:%S", time.localtime(epoch_time/1000))  # Add %Z to show timezone
        except:
            return "Could not convert - {}".format(epoch_time)

    # Converts a bar status ID number into a text description
    @staticmethod
    def getBarStatusDescription(id):

        binary = "{:b}".format(id)
        description = ""

        for bit_idx, bit_val in enumerate(reversed(binary)):
            if bit_val == '1':
                description += "{} ".format(Stream.status_bitmap[bit_idx])

        return description

    # Returns true if the tick is real-time
    @staticmethod
    def isTickRealtime(id):
        binary = "{:b}".format(id)
        return binary[::-1][1] == '1'

    # Returns true if the tick is the closing tick of the bar
    @staticmethod
    def isTickClose(id):
        binary = "{:b}".format(id)
        if len(binary) >= 5:
            return binary[::-1][4] == '1' or binary[::-1][3] == '1'
        elif len(binary) == 4:
            return binary[::-1][3] == '1'
        else:
            return False

    # Returns true if the tick is the opening tick of the bar
    # Note: It is possible for this to return true on the last
    # historical bar or real-time bars
    @staticmethod
    def isTickOpen(id):
        binary = "{:b}".format(id)
        # Tick is new and not closed
        return binary[::-1][0] == '1' and not Stream.isTickClose(id)


class UserQuestions:

    # Takes a list of Accounts (see Account class) and prompts the user to select
    # account number by entering the index number
    @staticmethod
    def askAccount(accounts):
        # Prompt for account selection
        for idx, account in enumerate(accounts):
            print("{}. {}".format(idx+1, account.number))
        try:
            #selection = int(input("Index of account to automate? ")) - 1
            account = accounts[0]
            logging.info("Account selected: {}".format(account.number))
        except:
            logging.error('Invalid account selection')
            print("Invalid selection")
            sys.exit(1)

        return account

    # Prompts the user to enter a symbol to automate
    @staticmethod
    def askSymbol():

        try:
            #user_input = input("Symbol to automate? ")
            symbol = 'SPY'

            # if user_input == "":
            #     logging.error('Symbol not specified')
            #     print("Symbol not specified")
            #     sys.exit(1)

            logging.info("Symbol to trade: {}".format(symbol))

        except:
            logging.error('Symbol input error')
            print("Symbol input error")
            sys.exit(1)

        return symbol

    # Prompts the user for a numerical quantity
    @staticmethod
    def askQuantity():
        try:
            #user_input = input("Quantity to automate? ")
            quantity = 0
            logging.info("Quantity to trade: {}".format(quantity))
        except:
            logging.error("Invalid quantity")
            print("Invalid quantity")
            sys.exit(1)

        return quantity


class Client():

    def __init__(self, refresh_token, user_id, account=None, symbol=None, quantity=None):

        logging.info('Initializing client')
        self.expiration = datetime.now()
        self.refresh_token = REFRESH_TOKEN
        self.refreshAccessToken(force_refresh=True)  # Set self.access_token
        self.user_id = user_id
        self.accounts = self.getAccounts()

        if account == None:
            self.account = UserQuestions.askAccount(self.accounts)
        else:
            self.account = account

        if symbol == None:
            self.symbol = UserQuestions.askSymbol()
        else:
            self.symbol = symbol.upper()

        if quantity == None:
            self.quantity = UserQuestions.askQuantity()
        else:
            self.quantity = int(quantity)  # integer

        self.symbol_asset_type = Client.getAssetTypeFromSymbol(self.symbol)

    def stream(self, symbol, bar_type, interval, days_back=5, session_template='Default', update_intrabar=True):

        logging.info('Calling Client.stream')

        self.refreshAccessToken()

        logging.info('Creating new Stream')

        stream = Stream(
            client=self,
            symbol=symbol,
            bar_type=bar_type,
            interval=interval,
            days_back=days_back,
            session_template=session_template,
            update_intrabar=update_intrabar
        )
        

        stream.stream()
        #self.stupidformat= stream.bar_data

    def submitOrder(self, account, asset_type, duration, order_type, quantity, symbol, trade_action, OSOs=[], gtd_date=None, limit_price=None, stop_price=None, order_confirm_id=None, route=None):

        self.refreshAccessToken()

        url = API_BASE_URL + '/orders'

        parameters = {
            'access_token': self.access_token
        }

        body = {
            'AccountKey': account.key,
            'AssetType': asset_type.upper(),
            'Duration': duration.upper(),
            'GTDDate': gtd_date,
            'LimitPrice': limit_price,
            'StopPrice': stop_price,
            'OrderConfirmId': order_confirm_id,
            'OrderType': order_type,
            'OSOs': OSOs,
            'Quantity': str(quantity),
            'Route': route,
            'Symbol': symbol.upper(),
            'TradeAction': trade_action
        }

        response = requests.post(url, json=body, params=parameters)

        try:
            response_json = response.json()
        except:
            response_json = response.text

        return response_json

    def updateOrder(self, order_id, new_price ):#account, asset_type, duration, order_type, quantity, symbol, trade_action, OSOs=[], gtd_date=None, limit_price=None, stop_price=None, order_confirm_id=None, route=None):

        self.refreshAccessToken()

        url = API_BASE_URL + '/orders/' + order_id

        parameters = {
            'access_token': self.access_token
        }

        body = {
            'AccountKey': account.key,
            'AssetType': asset_type.upper(),
            'Duration': duration.upper(),
            'GTDDate': gtd_date,
            'LimitPrice': limit_price,
            'StopPrice': stop_price,
            'OrderConfirmId': order_confirm_id,
            'OrderType': order_type,
            'OSOs': OSOs,
            'Quantity': str(quantity),
            'Route': route,
            'Symbol': symbol.upper(),
            'TradeAction': trade_action
        }

        response = requests.post(url, json=body, params=parameters)

        try:
            response_json = response.json()
        except:
            response_json = response.text

        return response_json

    # This method will go long if a long position does not already exist
    # If a long position already exists, no action is taken, else the
    # method will attempt to result in a long position with a quantity of
    # self.quantity
    def goLong(self):

        parent_trade_action = 'BUY'
        parent_quantity = self.quantity
        OSOs = []
        position = self.getPosition(
            self.account, self.symbol)

        # Check if position for trading symbol exists in account
        if position:
            # A long position exists no need to continue
            if position['LongShort'] == 'Long':
                logging.warn("Position is already long")
                return None
            if self.symbol_asset_type == "FU":
                # Set parent trade action to buy
                # Set parent quantity to short position quantity + client instance trade quantity
                parent_trade_action = "BUY"
                parent_quantity = abs(
                    position['Quantity']) + self.quantity
            elif self.symbol_asset_type == "EQ":
                # Since we are in a short position, set parent trade action to Buy to Cover
                # Use an OSO to buy
                # Set parent quantity to match quantity of the current short position
                parent_trade_action = 'BUYTOCOVER'
                parent_quantity = abs(position['Quantity'])

                OSOs = [
                    {
                        'Type': 'NORMAL',
                        'Orders': [
                            {
                                'AccountKey': self.account.key,
                                'AssetType': self.symbol_asset_type,
                                'Duration': 'DAY',
                                'OrderType': 'Market',
                                'Quantity': self.quantity,
                                'Symbol': self.symbol,
                                'TradeAction': 'BUY'
                            }]
                    }]
            else:
                # Parent order trade action
                if self.symbol_asset_type == "FU":
                    parent_trade_action = "BUY"
                elif self.symbol_asset_type == "EQ":
                    parent_trade_action = "BUY"
                else:
                    parent_trade_action = "BUYTOOPEN"

        logging.info("Going long {}".format(self.quantity))

        return self.submitOrder(
            account=self.account,
            asset_type=self.symbol_asset_type,
            duration="DAY",
            order_type="Market",
            OSOs=OSOs,
            quantity=parent_quantity,
            symbol=self.symbol,
            trade_action=parent_trade_action
        )

    # This method will go short if a short position does not already exist
    # If a short position already exists, no action is taken, else the
    # method will attempt to result in a short position with a quantity of
    # self.quantity
    def goShort(self):

        parent_trade_action = "SELLSHORT"
        parent_quantity = self.quantity
        OSOs = []
        position = self.getPosition(
            self.account, self.symbol)

        # Check if position for trading symbol exists in account
        if position:
            # A short position exists no need to continue
            if position['LongShort'] == 'Short':
                logging.warn("Position is already short")
                return None
            if self.symbol_asset_type == "FU":
                # Set parent trade action to sell
                # Set parent quantity to short position quantity + client instance trade quantity
                parent_trade_action = "SELL"
                parent_quantity = abs(
                    position['Quantity']) + self.quantity
            elif self.symbol_asset_type == "EQ":
                # Since we are in a long position, set parent trade action to sell
                # Use an OSO to sell short
                # Set parent quantity to match quantity of the current short position
                parent_trade_action = 'SELL'
                parent_quantity = abs(position['Quantity'])

                OSOs = [
                    {
                        'Type': 'NORMAL',
                        'Orders': [
                            {
                                'AccountKey': self.account.key,
                                'AssetType': self.symbol_asset_type,
                                'Duration': 'DAY',
                                'OrderType': 'Market',
                                'Quantity': self.quantity,
                                'Symbol': self.symbol,
                                'TradeAction': 'SELLSHORT'
                            }]
                    }]
        else:
            if self.symbol_asset_type == "FU":
                parent_trade_action = "SELL"
            elif self.symbol_asset_type == "EQ":
                parent_trade_action = "SELLSHORT"
            else:
                parent_trade_action = "SELLTOOPEN"

        logging.info("Going short {}".format(self.quantity))

        return self.submitOrder(
            account=self.account,
            asset_type=self.symbol_asset_type,
            duration="DAY",
            order_type="Market",
            OSOs=OSOs,
            quantity=parent_quantity,
            symbol=self.symbol,
            trade_action=parent_trade_action
        )

    # Gets a list of Account objects (see Account class)
    def getAccounts(self):

        self.refreshAccessToken()

        url = API_BASE_URL + f"/users/{self.user_id}/accounts"

        headers = {'content-type': 'application/json'}
        parameters = {
            'access_token': self.access_token
        }
        response = requests.get(url, params=parameters, headers=headers)

        if response.status_code != 200:
            raise Exception("Could not load accounts")

        # Create empty list to hold elements of type Account
        accounts = []

        # Loop through parsed responses and populate list with Accounts
        json_response = response.json()
        for data in json_response:
            account = Account(
                data['Name'],  # Synonymous with account number
                data['Alias'],
                data['Key'])
            accounts.append(account)

        return accounts

    def getPositions(self, account):

        self.refreshAccessToken()

        url = API_BASE_URL + f"/accounts/{account.key}/positions"

        headers = {'content-type': 'application/json'}
        parameters = {
            'access_token': self.access_token
        }
        response = requests.get(url, params=parameters, headers=headers)

        if response.status_code != 200:
            raise Exception("Could not load positions for account")

        json_response = response.json()

        return json_response

    def getPosition(self, account, symbol): #PU

        positions = self.getPositions(account)

        for position in positions:
            print(position)#
            current_symbol = position['Symbol']
            if symbol == current_symbol:
                return position

        return None

    def getSymbolsFromList(self, list): #PU

        self.refreshAccessToken()

        url = API_BASE_URL + f"/data/symbollists/{list}/symbols"

        headers = {'content-type': 'application/json'}
        parameters = {
            'access_token': self.access_token
        }

        response = requests.get(url, params=parameters, headers=headers)

        if response.status_code != 200:
            raise Exception(
                f"Could not get symbols in {list}"
            )

        return response.json()

    def getQuote(self, symbol):

        self.refreshAccessToken()

        url = API_BASE_URL + f"/data/quote/{symbol}"

        headers = {'content-type': 'application/json'}
        parameters = {
            'access_token': self.access_token
        }

        response = requests.get(url, params=parameters, headers=headers)

        if response.status_code != 200:
            raise Exception(
                f"Could not get quote for {symbol}"
            )

        return response.json()

    def refreshAccessToken(self, force_refresh=False):

        seconds_remaining = (self.expiration - datetime.now()).total_seconds()

        if (seconds_remaining <= 20 or force_refresh):
            logging.info("Refreshing access token")
            url = API_BASE_URL + "/security/authorize"

            headers = {'content-type': 'application/x-www-form-urlencoded'}
            parameters = {
                'grant_type': 'refresh_token',
                'client_id': API_KEY,
                'redirect_uri': REDIRECT_URI,
                'client_secret': SECRET_KEY,
                'refresh_token': self.refresh_token
            }

            response = requests.post(url, data=parameters, headers=headers)

            if response.status_code != 200:
                raise Exception("Could not refresh access token")

            data = response.json()
            exp_seconds = int(data['expires_in'])

            self.access_token = data['access_token']
            self.expiration = datetime.now() + timedelta(seconds=exp_seconds)

    # Determines asset type based on symbol string
    @staticmethod
    def getAssetTypeFromSymbol(symbol):

        # If symbol has space, it's an option symbol
        if " " in symbol:
            asset_type = "OP"
        # If symbol has no space and at least one digit, it's a futures symbol
        elif any(i.isdigit() for i in symbol):
            asset_type = "FU"
        # If symbol has no spaces and no digits, it's an equity symbol
        else:
            asset_type = "EQ"

        logging.info("Client.getAssetTypeFromSymbol({}) returning asset type {}".format(
            symbol, asset_type))

        return asset_type


# if __name__ == '__main__':

#     logging.basicConfig(
#         filename=LOG_FILE,
#         format='%(levelname)s - %(asctime)s - %(message)s',
#         datefmt='%d-%b-%y %H:%M:%S',
#         level=logging.DEBUG
#     )

#     client = Client(user_id=USER_ID, refresh_token=REFRESH_TOKEN)

#     # Example to submit an order
#     # client.submitOrder(
#     #     account=client.account,
#     #     asset_type=client.symbol_asset_type,
#     #     duration="DAY",
#     #     quantity=client.quantity,
#     #     symbol=client.symbol,
#     #     order_type="Limit",
#     #     limit_price="2847",
#     #     trade_action="BUY"
#     # )

#     client.stream(
#         symbol=client.symbol,
#         bar_type="Minute",
#         interval=5,
#         days_back=2,
#         update_intrabar=True
#     )

def run_server():
    # logging.basicConfig(
    #     filename=LOG_FILE,
    #     format='%(levelname)s - %(asctime)s - %(message)s',
    #     datefmt='%d-%b-%y %H:%M:%S',
    #     level=logging.DEBUG
    # )    
    # client = Client(user_id=USER_ID, refresh_token=REFRESH_TOKEN)    
    # Example to submit an order
    # client.submitOrder(
    #     account=client.account,
    #     asset_type=client.symbol_asset_type,
    #     duration="DAY",
    #     quantity=client.quantity,
    #     symbol=client.symbol,
    #     order_type="Limit",
    #     limit_price="2847",
    #     trade_action="BUY"
    # )   
    client.stream(
        symbol=client.symbol,
        bar_type="Minute",
        interval=5,
        days_back=2,
        update_intrabar=True
    )

logging.basicConfig(
    filename=LOG_FILE,
    format='%(levelname)s - %(asctime)s - %(message)s',
    datefmt='%d-%b-%y %H:%M:%S',
    level=logging.DEBUG
)    

#bar_data = pd.DataFrame()

client = Client(user_id=USER_ID, refresh_token=REFRESH_TOKEN)
# all_positions = client.getPositions(client.account)
# client.stream(
#     symbol=client.symbol,
#     bar_type="Minute",
#     interval=5,
#     days_back=2,
#     update_intrabar=True
# )

all_positions = client.getPositions(client.account)

def russell_data(all_positions_rd):
    # Convert list of dictionaries into list of lists
    OpenProfitLoss_list_rd = ['OpenProfitLoss']
    Quantity_list_rd = ['Quantity']
    Symbol_list_rd = ['Symbol']
    TimeStamp_list_rd = ['TimeStamp']
    
    for i in range(0,len(all_positions_rd),1):
        OpenProfitLoss_list_rd.append(all_positions_rd[i]['OpenProfitLoss'])
        Quantity_list_rd.append(all_positions_rd[i]['Quantity'])
        Symbol_list_rd.append(all_positions_rd[i]['Symbol'])
        TimeStamp_list_rd.append(all_positions_rd[i]['TimeStamp'])
    
    russell_data_list_rd = [OpenProfitLoss_list_rd, Quantity_list_rd, Symbol_list_rd,TimeStamp_list_rd]
        
    return russell_data_list_rd
        

my_thread_SFE = threading.Thread(target=run_server, daemon=True)

my_thread_SFE.start()
time.sleep(5)

######################################################### Data for Google
# russell_data_list = russell_data(all_positions)

# def read_ohlc(live_data_file_rohlc):
#     with open(live_data_file_rohlc, 'r') as f:
#         file_data = f.read()
    
#     file_list = file_data.split(', ')
    
#     return file_list[1:5]


# ohlc = read_ohlc(r"C:\Users\Charlie\Documents\CVE\Python\API\Combine API's\live_data.txt")

# realised_profit = 25036

symbols_list = []
for pos in all_positions:
    symbols_list.append(pos['Symbol'])

total_equity_df = pd.DataFrame(columns =symbols_list)

# while True:
#     open_pos_profit = 0
#     # ohlc = read_ohlc(r"C:\Users\Charlie\Documents\CVE\Python\API\Combine API's\live_data.txt")
#     #calculate_current_profit(ohlc[3], shares, entry_price)
#     all_positions = client.getPositions(client.account)
#     new_row = {}
#     for pos in all_positions:
#         open_pos_profit += pos['OpenProfitLoss']
#         new_row[pos['Symbol']] = pos['OpenProfitLoss']
#     total_equity_df.loc[datetime.now()] = new_row
#     print(new_row)
#     total_equity_df.to_csv()
#     time.sleep(20)
    









