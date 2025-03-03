
## **Singleton Pattern Overview**

The Singleton pattern ensures that a class has only one instance and provides a global point of access to it. This is especially useful when you need a single shared resource, such as:

- **Configuration Managers:** Ensuring consistency of configuration across the application.
- **Logging:** Providing a central logger for all components.
- **Database Connection Pools:** Managing connections without creating duplicates.
- **Caching:** Using a single cache instance to avoid inconsistent data.

### **Why and Where It’s Used**

- **In Microservices:**
  Microservices often need to manage resources (e.g., logging, configuration, security) in a consistent manner. A singleton ensures that these shared services are created only once per service instance, reducing overhead and complexity. For example, a logging component in a Spring Boot microservice is typically a singleton so that all parts of the application log in a uniform way.

- **In System Design:**
  A singleton helps in reducing memory footprint and ensures that global states (like a connection pool or configuration) remain consistent throughout the application lifecycle. This is vital in large-scale systems where multiple parts of the system might interact with the same resource.

- **Benefits:**
  - **Resource Efficiency:** Only one instance is created and reused.
  - **Consistency:** All clients share the same instance, ensuring a unified behavior.
  - **Thread Safety:** Properly implemented singletons (using techniques such as double-checked locking) guarantee safe access in multi-threaded environments.
  - **Easy Access:** The static method `getInstance()` provides a global access point to the instance.

---

## **Detailed Code Explanation**

Below is the code with a line-by-line explanation.

### **Singleton Class**

```java
package Singleton;
```
- **Package Declaration:**
  This places the class in the `Singleton` package, grouping related classes together.

```java
import java.io.FileWriter;
import java.io.PrintWriter;
```
- **Imports:**
  These import the necessary I/O classes used to write logs to a file.

---

```java
// Imp - This class behaves as a @Bean or @Configuration class (having only one instance across entire application)
public class Singleton {
```
- **Class Declaration:**
  The class is named `Singleton`. A comment indicates that this class is intended to behave like a Spring Boot `@Bean` or configuration class, meaning it should have only one instance throughout the application.

---

```java
    // volatile ensures any thread reading the variable sees the most up-to-date value (Read repair)
    private static volatile Singleton activeInstance;       // variable to store the active singleton instance
```
- **Singleton Instance Field:**
  - **`private static volatile`:**
    - **`private`:** The instance is not accessible outside the class.
    - **`static`:** Belongs to the class itself rather than any instance.
    - **`volatile`:** Guarantees that changes to `activeInstance` are visible to all threads immediately. This is essential for correct behavior in a multi-threaded environment.
  - **Purpose:**
    This variable holds the single instance of the `Singleton` class.

---

```java
    public static final String LOG_FILE = "Singleton/application.log";
```
- **Log File Path:**
  A public constant string that defines the path to the log file. Using a constant here makes the log file location easily configurable and accessible.

---

```java
    private PrintWriter writer;     // Print writer created
```
- **PrintWriter Field:**
  An instance variable to hold a `PrintWriter` object, which will be used to write log messages to the specified file.

---

```java
    // private constructor to prevent instantiation
    private Singleton() {
        try {
            FileWriter fileWriter = new FileWriter(LOG_FILE, true);     // Opening a file in append mode
            writer = new PrintWriter(fileWriter, true);     // Allows auto-flush in printing
        } catch (Exception e) {
            e.printStackTrace();
        }
    }
```
- **Private Constructor:**
  - **Purpose:**
    The constructor is private, which prevents any other class from creating a new instance of `Singleton` using the `new` keyword.
  - **Inside the Constructor:**
    - **FileWriter Initialization:** Opens the log file in append mode (the `true` parameter) so that new logs are added to the end of the file.
    - **PrintWriter Initialization:** Wraps the `FileWriter` and enables auto-flushing, meaning that every call to `println` immediately writes data to the file.
  - **Error Handling:**
    Any exceptions thrown during file operations are caught and printed to the standard error stream.

---

```java
    public static Singleton getInstance() {
        if(activeInstance == null) {        // When current instance is not yet created
            synchronized (Singleton.class) {        // Locks the code block, preventing multiple threads to enter and create many instances
                // Imp - When the instance is null, create the first and only instance (critical section)
                if(activeInstance == null)
                    activeInstance = new Singleton();
            }
        }
        return activeInstance;      // Return the singleton instance
    }
```
- **Static Access Method `getInstance()`:**
  - **First Check:**
    `if(activeInstance == null)` verifies if an instance has not yet been created. This is known as lazy initialization.
  - **Synchronized Block:**
    The block is synchronized on the `Singleton.class`, ensuring that only one thread can execute it at a time. This prevents race conditions when multiple threads try to create an instance concurrently.
  - **Double-Checked Locking:**
    Inside the synchronized block, there is another check (`if(activeInstance == null)`) before creating the instance. This double-check is critical because once a thread enters the synchronized block and creates an instance, any subsequent threads must not create a new one.
  - **Return Statement:**
    After ensuring that an instance exists, it returns the single instance.

---

```java
    public void log(String log) {
        writer.println(log);
        System.out.println("Log : " + log);
        return;
    }
```
- **Logging Method:**
  - **Function:**
    The `log` method writes the provided log message both to the log file (using `writer.println`) and to the standard output (using `System.out.println`).
  - **Auto-flush:**
    Because the `PrintWriter` was created with auto-flush enabled, every log entry is immediately written to the file.

---

```java
    public static int getHashCode() {       // Generate and provide the hash code (when same instances the hash code are same)
        return activeInstance != null ? activeInstance.hashCode() : -1;
    }
```
- **Static Method to Get Hash Code:**
  This method returns the hash code of the active singleton instance. If the instance hasn’t been created yet, it returns -1.
  - **Purpose:**
    The hash code is used to verify that every call to `getInstance()` returns the same object (i.e., they have the same memory address).

---

```java
    public void close() {
        writer.close();
    }
```
- **Close Method:**
  This method closes the `PrintWriter`, releasing the file resource. It is good practice to release resources when they are no longer needed.

---

## **Logger Class (Driver Code)**

```java
package Singleton;

public class Logger {
```
- **Logger Class:**
  A simple class that demonstrates the usage of the `Singleton` class.

---

```java
    public static void main(String[] args) {
```
- **Main Method:**
  The entry point of the program, where the control flow starts.

---

```java
        Singleton instance1 = Singleton.getInstance();
```
- **First Instance Retrieval:**
  The `getInstance()` method is called for the first time. Since no instance exists yet, the singleton is created.
  - **Control Flow:**
    - Checks if `activeInstance` is null.
    - Enters the synchronized block.
    - Double-checks and creates a new `Singleton` instance.
    - Returns the instance.

---

```java
        instance1.log("First instance log");
```
- **Logging Using First Instance:**
  The `log` method is called on `instance1` to log the message "First instance log". This writes the message to both the log file and the console.

---

```java
        System.out.println(Singleton.getHashCode());
```
- **Printing the Hash Code:**
  Prints the hash code of the singleton instance. This value will help us confirm that any subsequent calls to `getInstance()` return the same object.

---

```java
        Singleton instance2 = Singleton.getInstance();
```
- **Second Instance Retrieval:**
  Calls `getInstance()` again. Since the singleton instance is already created, the method quickly returns the existing instance without entering the synchronized block.

---

```java
        instance2.log("Second instance log");
```
- **Logging Using Second Instance:**
  The log method is called on `instance2`. Although called on a different reference, it’s the same underlying instance as `instance1`.

---

```java
        instance1.log("First instance write");
```
- **Additional Logging:**
  Another log call using the first instance. This further demonstrates that both references (`instance1` and `instance2`) are working with the same object.

---

```java
        System.out.println(Singleton.getHashCode());
```
- **Verifying the Hash Code:**
  Prints the hash code again. It should match the previous hash code, confirming that both calls to `getInstance()` returned the same instance.

---

```java
        System.out.println(instance1 instanceof Singleton && instance2 instanceof Singleton);
```
- **Type Check:**
  Checks whether both `instance1` and `instance2` are instances of `Singleton`. This should print `true`.

---

```java
        System.out.println(instance1 == instance2);
```
- **Reference Equality Check:**
  Checks if `instance1` and `instance2` refer to the exact same object. This should also print `true`, confirming the singleton behavior.

---

### **Control Flow Summary**

1. **First Call to `getInstance()`:**
   - The method checks if `activeInstance` is `null`.
   - It enters the synchronized block because no instance exists.
   - Double-check passes, a new `Singleton` instance is created.
   - The instance is stored in `activeInstance` and returned.

2. **Subsequent Calls to `getInstance()`:**
   - The method finds `activeInstance` is not `null`.
   - It immediately returns the already-created instance, bypassing the synchronized block.

3. **Logging and Verification:**
   - The `log` method writes messages to the log file and console.
   - The `getHashCode()` method returns the same hash code, proving that both references point to the same instance.
   - Additional checks using `instanceof` and reference equality confirm the singleton property.

---

## **Benefits in Microservices and System Design**

- **Resource Optimization:**
  Ensures that only one instance of a resource (such as a logger or configuration service) is created, which is particularly important in microservices to avoid excessive resource usage.

- **Consistency:**
  A singleton provides a centralized mechanism to manage shared resources, ensuring consistency across different parts of the application. For example, all microservices might share a common logging configuration.

- **Thread Safety:**
  The implementation uses the `volatile` keyword and double-checked locking to guarantee that multiple threads do not create multiple instances simultaneously.

- **Ease of Use in Spring Boot:**
  In a Spring Boot application, many beans (like data sources or loggers) are singletons by default. This pattern aligns well with Spring’s dependency injection, making it easier to manage application-wide components.
