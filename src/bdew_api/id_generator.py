import hmac
import hashlib
import datetime
import re
import secrets
import string
import uuid

class IDGenerator:
    """Generate various types of IDs for components."""
    
    @staticmethod
    def generate_hmac_id(prefix: str, counter, length: int = 8) -> str:
        """
        Generate HMAC-based ID (deterministic, appears random, cryptographically secure).
        
        RECOMMENDED for your use case (up to 1000 versions per component).
        
        Args:
            prefix: Component prefix (e.g., 'aemt', 'smgw')
            counter: Sequential counter (0-999 or similar)
            length: Length of hex suffix (default 8, minimum 5)
        
        Returns:
            ID in format: prefix-hexstring
        
        Example:
            generate_hmac_id('aemt', 42, 8) -> 'aemt-26aa1cdf'
        """
        if length < 5:
            raise ValueError(f"Length must be at least 5, got {length}")
        
        key = prefix.encode()
        if type(counter) is int:
            message = str(counter).encode()
        else:
            message = counter.encode()
        h = hmac.new(key, message, hashlib.sha256)
        hex_digest = h.hexdigest()
        return f"{prefix}{hex_digest[:length]}"
    
    @staticmethod
    def generate_hmac_group_id(key: str, counter: int, length: int = 2) -> str:
        """
        Generates hmac for group id, so namespace to identify components belonging to each other
        """
        if length < 2:
            raise ValueError(f"Length must be at least 5, got {length}")
        
        k = key.encode()
        message = str(counter).encode()
        h = hmac.new(k, message, hashlib.sha256)
        hex_digest = h.hexdigest()
        return f"{hex_digest[:length]}"

    @staticmethod
    def generate_random_id(prefix: str, length: int = 8) -> str:
        """
        Generate cryptographically random ID (non-deterministic, stateless).
        
        Use if you don't need reproducible IDs from a counter.
        
        Args:
            prefix: Component prefix (e.g., 'aemt', 'smgw')
            length: Length of hex suffix (default 8)
        
        Returns:
            ID in format: prefix-hexstring
        
        Example:
            generate_random_id('aemt', 8) -> 'aemt-db897150'
        """
        random_hex = secrets.token_hex(length // 2)
        return f"{prefix}{random_hex[:length]}"
    
    @staticmethod
    def generate_sequential_id(prefix: str, counter: int, width: int = 3) -> str:
        """
        Generate simple sequential ID (human-readable, predictable).
        
        Use only if you need maximum simplicity and don't mind predictability.
        
        Args:
            prefix: Component prefix (e.g., 'aemt', 'smgw')
            counter: Sequential counter (0-999 or similar)
            width: Number of zero-padded digits (default 3 for 0-999)
        
        Returns:
            ID in format: prefix-NNN
        
        Example:
            generate_sequential_id('aemt', 42, 3) -> 'aemt-042'
        """
        return f"{prefix}{counter:0{width}d}"

    @staticmethod
    def generate_transaction_id() -> str:
        #uuid4(): Generate a random UUID in a cryptographically-secure method according to RFC 9562, §5.4.
        transaction_id = uuid.uuid4()
        return str(transaction_id)

    @staticmethod
    def generate_location_id(type=None) -> str:
        #regex: "C[A-Z0-9]{9}[A-Z0-9]{1}"
        #request at BNetzA (``type`` is accepted for call-site compatibility with
        #the pEMT's id_generator, which passes a prefix hint like "cb"; unused)
        digits = []
        while len(digits) <= 10:
            #digits.append(secrets.randbelow(10))
            sequence = string.ascii_uppercase+string.digits
            digits.append(secrets.choice(sequence))
        loc_str = "".join([str(d) for d in digits])
        location_id = "C"+loc_str
        return location_id

    @staticmethod
    def generate_partner_id() -> int:
        #4041407000008
        #Marktpartner-ID: Strom (BDEW): 99 + [0-8]{1} +[0-9]{1}
        seq_digit = ["0","1","2","3","4","5","6","7","8"]
        digit = secrets.choice(seq_digit)
        seq_digits = string.digits
        digits = []
        while len(digits) <= 13:
            digits.append(secrets.choice(seq_digits))
        digits_str = "".join([str(d) for d in digits])
        partner_id = int("99"+digit + digits_str)
        return partner_id

    @staticmethod
    def generate_datetimestamp() -> str:
        dt = datetime.datetime.now()
        dt_str = str(dt)
        pattern_date = "\\d{4}-\\d{2}-\\d{2}"
        date = re.search(pattern_date,dt_str).group()
        pattern_time = "\\d{2}:\\d{2}:\\d{2}.\\d{4}"
        time = re.search(pattern_time,dt_str).group()
        datetimestamp = date + "T" + time + "Z"
        return datetimestamp

def main():
    id_generator = IDGenerator()

    print(id_generator.generate_hmac_id("mme", 42, 8))
    print(id_generator.generate_hmac_id("smgw", 42, 8))
    print(id_generator.generate_hmac_id("aemt", 42, 8))
    print(id_generator.generate_hmac_id("gwa", 42, 8))
    print(id_generator.generate_hmac_id("controlbox", 42, 8))
    # Test could be replaced by the switch id or something that allows one to
    # group the components together from the grid topology
    print(id_generator.generate_hmac_group_id("test", 1, 3))
    print(id_generator.generate_transaction_id())
    print(id_generator.generate_location_id())
    print(id_generator.generate_partner_id())
    print(id_generator.generate_datetimestamp())


if __name__ == "__main__":
    main()
