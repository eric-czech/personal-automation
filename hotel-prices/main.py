import fire

class HotelPrices:
  
    def run(self, name: str) -> None:
        print(f'Hello {name}!')

if __name__ == '__main__':
    fire.Fire(HotelPrices)