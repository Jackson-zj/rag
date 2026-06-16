ARG DOCKERHUB_LIBRARY_PREFIX=
FROM ${DOCKERHUB_LIBRARY_PREFIX}maven:3.9-eclipse-temurin-17 AS build
WORKDIR /workspace
RUN mkdir -p /root/.m2 && cat > /root/.m2/settings.xml <<'EOF'
<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.2.0 https://maven.apache.org/xsd/settings-1.2.0.xsd">
  <mirrors>
    <mirror>
      <id>aliyunmaven</id>
      <mirrorOf>central</mirrorOf>
      <name>Aliyun Maven Central Mirror</name>
      <url>https://maven.aliyun.com/repository/central</url>
    </mirror>
    <mirror>
      <id>aliyun-public</id>
      <mirrorOf>public</mirrorOf>
      <name>Aliyun Maven Public Mirror</name>
      <url>https://maven.aliyun.com/repository/public</url>
    </mirror>
  </mirrors>
</settings>
EOF
COPY pom.xml .
COPY backend-java/pom.xml ./backend-java/pom.xml
COPY backend-java/src ./backend-java/src
RUN mvn -q -pl backend-java -am -DskipTests package

ARG DOCKERHUB_LIBRARY_PREFIX=
FROM ${DOCKERHUB_LIBRARY_PREFIX}eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /workspace/backend-java/target/backend-java-0.1.0.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
